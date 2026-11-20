// SPDX-License-Identifier: MIT
// Copyright (c) 2026 conniecombs

package core

import (
	"net/url"
	"path"
	"regexp"
	"sort"
	"strings"
	"sync"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

// File match modes of a resolve_spec.
const (
	matchModeFilename    = "filename"
	matchModeContains    = "contains"
	matchModeFirst       = "first"
	matchModeSingle      = "single"
	matchModeUploadOrder = "upload_order"
)

// ResolveNeedsSequentialUploads reports whether a job's files must upload one
// at a time. upload_order gives the n-th upload of the job to finish the n-th
// entry of the result page, which is only well defined when uploads in the
// shared session do not overlap.
func ResolveNeedsSequentialUploads(spec *BatchResolveSpec) bool {
	return spec != nil && normalizeMatchMode(spec.FileMatchMode) == matchModeUploadOrder
}

func normalizeMatchMode(mode string) string {
	mode = strings.ToLower(strings.TrimSpace(mode))
	if mode == "" {
		return matchModeFilename
	}
	return mode
}

// resolveEntry is one image a result page lists.
type resolveEntry struct {
	ImageURL string
	ThumbURL string
	Name     string
}

// extractResolveEntries returns the page's entries in page order, one per
// image URL.
func extractResolveEntries(re *regexp.Regexp, body string) []resolveEntry {
	var entries []resolveEntry
	index := make(map[string]int)
	for _, match := range re.FindAllStringSubmatch(body, -1) {
		entry := resolveEntry{
			ImageURL: namedGroup(re, match, "image_url"),
			ThumbURL: namedGroup(re, match, "thumb_url"),
			Name:     namedGroup(re, match, "filename"),
		}
		if entry.ImageURL == "" {
			continue
		}
		if i, seen := index[entry.ImageURL]; seen {
			if entries[i].ThumbURL == "" {
				entries[i].ThumbURL = entry.ThumbURL
			}
			if entries[i].Name == "" {
				entries[i].Name = entry.Name
			}
			continue
		}
		index[entry.ImageURL] = len(entries)
		entries = append(entries, entry)
	}
	return entries
}

// Name match strength, best first. A file takes the best entry it can find;
// a looser match is only used when nothing better is listed.
const (
	noMatch      = 0
	exactMatch   = 1 // same file name, ignoring case
	similarMatch = 2 // same name once punctuation is ignored (the host sanitized it)
	looseMatch   = 3 // the host's name contains the file's name (for example a prefix)
)

type nameForms struct {
	exact   string
	similar string
}

// localNameForms normalizes a local file name. It is never parsed as a URL:
// "Scan #2.jpg" is a name, not a link with a fragment.
func localNameForms(name string) nameForms {
	name = strings.TrimSpace(name)
	if i := strings.LastIndexAny(name, `/\`); i >= 0 {
		name = name[i+1:]
	}
	return newNameForms(name)
}

// pageNameForms normalizes a name taken from a result page. Values that are
// links are reduced to the last path segment; percent-escapes are decoded.
func pageNameForms(value string) nameForms {
	value = strings.TrimSpace(value)
	if strings.Contains(value, "://") || strings.HasPrefix(value, "/") {
		if parsed, err := url.Parse(value); err == nil && parsed.Path != "" {
			value = path.Base(parsed.EscapedPath())
		}
	}
	if unescaped, err := url.PathUnescape(value); err == nil {
		value = unescaped
	}
	return newNameForms(strings.TrimSuffix(strings.ToLower(value), ".html"))
}

// newNameForms compares names in Unicode NFC: macOS file names are often
// decomposed ("e" + U+0301) while hosts list the composed "é".
func newNameForms(name string) nameForms {
	exact := norm.NFC.String(strings.ToLower(strings.TrimSpace(name)))
	similar := strings.Join(strings.FieldsFunc(exact, func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	}), " ")
	return nameForms{exact: exact, similar: similar}
}

func nameMatch(page, local nameForms) int {
	if page.exact == "" || local.exact == "" {
		return noMatch
	}
	if page.exact == local.exact {
		return exactMatch
	}
	if local.similar == "" {
		return noMatch
	}
	if page.similar == local.similar {
		return similarMatch
	}
	if strings.Contains(" "+page.similar+" ", " "+local.similar+" ") {
		return looseMatch
	}
	return noMatch
}

// entryMatch is the best match between an entry (its page name, else the last
// segment of its link) and a local file name.
func entryMatch(entry resolveEntry, local nameForms) int {
	best := noMatch
	for _, value := range []string{entry.Name, entry.ImageURL} {
		if strings.TrimSpace(value) == "" {
			continue
		}
		if tier := nameMatch(pageNameForms(value), local); tier != noMatch && (best == noMatch || tier < best) {
			best = tier
		}
	}
	return best
}

// resolveState is shared by every file of one upload job. Its claims make
// sure two files of the job never get the same result-page entry, even when
// their lookups run concurrently, and it records the order in which the job's
// uploads finished.
type resolveState struct {
	mu            sync.Mutex
	claimed       map[string]string // entry image URL -> file
	claimedThumbs map[string]string // thumbnail URL -> file
	resolved      map[string]bool   // files that hold an entry
	finished      map[string]int    // file -> position among finished uploads
}

func newResolveState() *resolveState {
	return &resolveState{
		claimed:       make(map[string]string),
		claimedThumbs: make(map[string]string),
		resolved:      make(map[string]bool),
		finished:      make(map[string]int),
	}
}

var resolveStateInit sync.Mutex

// jobResolveState returns the job's shared resolve state, creating it on
// first use. Safe for the job's concurrent file workers.
func jobResolveState(job *JobRequest) *resolveState {
	resolveStateInit.Lock()
	defer resolveStateInit.Unlock()
	if job.resolveState == nil {
		job.resolveState = newResolveState()
	}
	return job.resolveState
}

// recordFinished notes that fp's upload has finished, after every upload of
// the job recorded before it.
func (s *resolveState) recordFinished(fp string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, done := s.finished[fp]; !done {
		s.finished[fp] = len(s.finished)
	}
}

// resolveMatcher assigns result-page entries to a job's files.
type resolveMatcher struct {
	mode  string
	names map[string]nameForms // every file of the job -> its name
	state *resolveState
}

func newResolveMatcher(mode string, fileNames map[string]string, state *resolveState) *resolveMatcher {
	names := make(map[string]nameForms, len(fileNames))
	for fp, name := range fileNames {
		names[fp] = localNameForms(name)
	}
	return &resolveMatcher{mode: normalizeMatchMode(mode), names: names, state: state}
}

func (m *resolveMatcher) usesNames() bool {
	return m.mode != matchModeFirst && m.mode != matchModeSingle && m.mode != matchModeUploadOrder
}

func (m *resolveMatcher) allowLoose(final bool) bool {
	return final || m.mode == matchModeContains
}

// position is where fp's upload finished among the job's uploads; files whose
// upload has not finished sort last.
func (m *resolveMatcher) position(fp string) int {
	if pos, ok := m.state.finished[fp]; ok {
		return pos
	}
	return int(^uint(0) >> 1)
}

func (m *resolveMatcher) byPosition(files []string) []string {
	ordered := append([]string(nil), files...)
	sort.SliceStable(ordered, func(i, j int) bool { return m.position(ordered[i]) < m.position(ordered[j]) })
	return ordered
}

// assign picks an entry for each pending file and claims it. final is the
// last look at the page, which also accepts loose name matches.
func (m *resolveMatcher) assign(entries []resolveEntry, pending []string, final bool) map[string]resolveEntry {
	m.state.mu.Lock()
	defer m.state.mu.Unlock()
	assigned := make(map[string]resolveEntry)
	for _, fp := range m.byPosition(pending) {
		entry, ok := m.choose(fp, entries, final)
		if !ok {
			continue
		}
		m.state.claimed[entry.ImageURL] = fp
		m.state.resolved[fp] = true
		assigned[fp] = entry
	}
	return assigned
}

func (m *resolveMatcher) choose(fp string, entries []resolveEntry, final bool) (resolveEntry, bool) {
	switch m.mode {
	case matchModeUploadOrder:
		return m.chooseByUploadOrder(fp, entries)
	case matchModeFirst, matchModeSingle:
		for _, entry := range entries {
			if m.state.claimed[entry.ImageURL] == "" {
				return entry, true
			}
		}
		return resolveEntry{}, false
	default:
		return m.chooseByName(fp, entries, final)
	}
}

// chooseByUploadOrder gives the n-th finished upload the n-th entry. A page
// with a single entry belongs to that one upload.
func (m *resolveMatcher) chooseByUploadOrder(fp string, entries []resolveEntry) (resolveEntry, bool) {
	if len(entries) == 1 {
		if m.state.claimed[entries[0].ImageURL] == "" {
			return entries[0], true
		}
		return resolveEntry{}, false
	}
	pos, ok := m.state.finished[fp]
	if !ok || pos >= len(entries) || m.state.claimed[entries[pos].ImageURL] != "" {
		return resolveEntry{}, false
	}
	return entries[pos], true
}

func (m *resolveMatcher) chooseByName(fp string, entries []resolveEntry, final bool) (resolveEntry, bool) {
	local, ok := m.names[fp]
	if !ok {
		return resolveEntry{}, false
	}
	best := noMatch
	var candidates []resolveEntry
	for _, entry := range entries {
		if m.state.claimed[entry.ImageURL] != "" {
			continue
		}
		tier := entryMatch(entry, local)
		if tier == noMatch || (tier == looseMatch && !m.allowLoose(final)) {
			continue
		}
		if m.reservedForAnother(entry, fp, tier) {
			continue
		}
		switch {
		case best == noMatch || tier < best:
			best, candidates = tier, []resolveEntry{entry}
		case tier == best:
			candidates = append(candidates, entry)
		}
	}
	if len(candidates) == 0 {
		return resolveEntry{}, false
	}
	// Files of the job with the same name whose uploads finished earlier take
	// the earlier entries, so the host's listing order decides between them.
	if ahead := m.sameNameFilesAhead(fp, candidates[0], best); ahead < len(candidates) {
		return candidates[ahead], true
	}
	if final {
		return candidates[len(candidates)-1], true
	}
	return resolveEntry{}, false
}

// reservedForAnother reports whether entry is held back for another file of
// the job that matches it better than fp does. Only a file whose upload has
// finished and that holds no entry yet can hold one back: a file still
// queued, or whose upload failed, is not on the page to be matched.
func (m *resolveMatcher) reservedForAnother(entry resolveEntry, fp string, tier int) bool {
	for other, forms := range m.names {
		if other == fp || m.state.resolved[other] {
			continue
		}
		if _, finished := m.state.finished[other]; !finished {
			continue
		}
		if otherTier := entryMatch(entry, forms); otherTier != noMatch && otherTier < tier {
			return true
		}
	}
	return false
}

func (m *resolveMatcher) sameNameFilesAhead(fp string, entry resolveEntry, tier int) int {
	mine := m.position(fp)
	ahead := 0
	for other, forms := range m.names {
		if other == fp || m.state.resolved[other] || m.position(other) >= mine {
			continue
		}
		if entryMatch(entry, forms) == tier {
			ahead++
		}
	}
	return ahead
}

// assignThumbs fills missing thumbnails from a separate thumbnail extractor.
func (m *resolveMatcher) assignThumbs(thumbs []resolveEntry, results map[string][2]string, final bool) {
	m.state.mu.Lock()
	defer m.state.mu.Unlock()
	var waiting []string
	for fp, pair := range results {
		if pair[1] == "" {
			waiting = append(waiting, fp)
		}
	}
	waiting = m.byPosition(waiting)
	for _, thumb := range thumbs {
		if len(waiting) == 0 {
			return
		}
		if m.state.claimedThumbs[thumb.ThumbURL] != "" {
			continue
		}
		pick := -1
		if !m.usesNames() {
			pick = 0
		} else {
			best := noMatch
			for i, fp := range waiting {
				tier := entryMatch(resolveEntry{Name: thumb.Name, ImageURL: thumb.ThumbURL}, m.names[fp])
				if tier == noMatch || (tier == looseMatch && !m.allowLoose(final)) {
					continue
				}
				if best == noMatch || tier < best {
					best, pick = tier, i
				}
			}
		}
		if pick < 0 {
			continue
		}
		fp := waiting[pick]
		results[fp] = [2]string{results[fp][0], thumb.ThumbURL}
		m.state.claimedThumbs[thumb.ThumbURL] = fp
		waiting = append(waiting[:pick], waiting[pick+1:]...)
	}
}

// extractThumbEntries returns a thumbnail extractor's matches in page order.
func extractThumbEntries(re *regexp.Regexp, body string) []resolveEntry {
	var thumbs []resolveEntry
	for _, match := range re.FindAllStringSubmatch(body, -1) {
		thumbURL := namedGroup(re, match, "thumb_url")
		if thumbURL == "" {
			continue
		}
		thumbs = append(thumbs, resolveEntry{ThumbURL: thumbURL, Name: namedGroup(re, match, "filename")})
	}
	return thumbs
}

// expectedFileNames maps each file to the name the host should list it under.
func expectedFileNames(files []string, fileNames map[string]string) map[string]string {
	names := make(map[string]string, len(files))
	for _, fp := range files {
		name := strings.TrimSpace(fileNames[fp])
		if name == "" {
			name = fileBaseName(fp)
		}
		names[fp] = name
	}
	return names
}

func fileBaseName(fp string) string {
	if i := strings.LastIndexAny(fp, `/\`); i >= 0 {
		return fp[i+1:]
	}
	return fp
}
