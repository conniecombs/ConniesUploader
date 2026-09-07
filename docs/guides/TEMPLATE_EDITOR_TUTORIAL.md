# Template Editor & Formats Tutorial

This guide is a complete, beginner-friendly, and "dummy-proof" manual for mastering the **Template Editor** in Connie's Uploader. It covers everything from basic placeholder substitution to advanced loop constructs, custom separators, conditional logic, and multi-format output.

---

## Table of Contents

1. [Mental Model & Core Concepts](#1-mental-model--core-concepts)
2. [Tour of the Template Editor Interface](#2-tour-of-the-template-editor-interface)
3. [The Golden Rules of Output Formats](#3-the-golden-rules-of-output-formats)
4. [Placeholders & Variables Reference](#4-placeholders--variables-reference)
5. [Working with Loops (`[for image]` & `[for cover]`)](#5-working-with-loops-for-image--for-cover)
6. [Working with Conditionals (`[if]` & `[else]`)](#6-working-with-conditionals-if--else)
7. [Copy & Paste Recipes](#7-copy--paste-recipes)
8. [Common Pitfalls & Troubleshooting Checklist](#8-common-pitfalls--troubleshooting-checklist)

---

## 1. Mental Model & Core Concepts

When you upload a batch of images with Connie's Uploader, each image host provides links (such as a thumbnail URL, a viewer page URL, and sometimes a direct image link). The **Template Engine** takes those raw links and wraps them into a finished text block ready for forums, Markdown files, or HTML pages.

A template is made of three kinds of text:

```text
[center][b]#batch_name#[/b]                <-- 1. Literal Text & Formatting Tags (e.g. BBCode, HTML, Markdown)
[if folder_size]Size: #folder_size#[/if]   <-- 2. Conditionals ([if]...[/if])
[for image separator=space]                <-- 3. Loops ([for image]...[/for])
[url=#image_url#][img]#thumb_url#[/img][/url]
[/for][/center]
```

### The Three Content Types

1. **Literal Text & Tags**: Characters like `[b]`, `**`, `[center]`, spaces, and newlines that are passed directly to your final output.
2. **Placeholders (`#variable#`)**: Special tags surrounded by `#` that the app replaces with real values (like `#batch_name#`, `#thumb_url#`, or `#folder_size#`).
3. **Control Blocks (`[if]` and `[for]`)**: Directives that instruct Connie's Uploader how to repeat images or conditionally hide lines. **These tags are processed and removed by Connie's Uploader before saving or posting—they will never be visible on forum posts.**

> [!TIP]
> **The Golden Rule for Beginners:** Before editing any built-in template, always click **Duplicate** or **Save As New...**. That way you have a safe sandbox to test in and the default templates remain intact.

---

## 2. Tour of the Template Editor Interface

Access the editor from the menu bar: **Tools > Template Editor**.

```
+---------------------------------------------------------------------------------------+
| Edit Format: [ BBCode v ]  Category: [ All v ]  Search: [ ............. ]             |
+---------------------------------------------------------------------------------------+
| Saved Templates: [ ViperGirls Gallery Post v ] [Load] [Duplicate] [Rename] [Delete]   |
|                  [Import] [Export]                                                    |
+---------------------------------------------------------------------------------------+
| [B] [I] [U] [Color] | Size: [ 2 v ] Font: [ Segoe UI v ]                              |
+---------------------------------------------------------------------------------------+
| Placeholders: Category: [ Images v ]                                                  |
| [All Images]   [Full Images]   [All Covers]   [Cover{s}]                              |
| [Cover Count]  [Image URL]     [Thumb URL]    [Direct URL]                            |
| [Thumb Size]   [Image Count]   [Folder Size]  [Cover Loop]                            |
| [Loop: Newline][Loop: Blank]   [Loop: Space]                                          |
+---------------------------------------------------------------------------------------+
|                                                                                       |
|   (Template Code Editor Area - Consolas Font)                                         |
|                                                                                       |
+---------------------------------------------------------------------------------------+
| [Preview in Browser] [Copy Preview Output] [Restore Defaults]  [Save Current] [Save As New...] |
+---------------------------------------------------------------------------------------+
```

### Key Controls & What They Do

* **Edit Format / Saved Templates**: Choose which template you are editing.
* **Toolbar (`[B]`, `[I]`, `[U]`, `[Color]`, `Size`, `Font`)**: Highlights selected text in the editor and wraps it in the correct syntax for the active template format (BBCode tags for forum formats, Markdown tags for Markdown formats, HTML tags for HTML formats).
* **Placeholders Panel**: Click any button to instantly insert that variable or loop snippet at your text cursor. Use the category dropdown (`Images`, `Gallery`, `Batch`, `Service`, `ViperGirls`) to find more variables.
* **Preview in Browser**: Opens your default browser displaying a side-by-side view: the rendered visual preview on top, and the raw generated text below it.
  > [!IMPORTANT]
  > Make sure you have at least one image in the main window queue before previewing, so the preview has real data to display!
* **Copy Preview Output**: Compiles the template against the current queue data and copies the raw output text straight to your clipboard for fast testing.
* **Save Current vs. Save As New...**: `Save Current` overwrites the active template; `Save As New...` prompts for a new name and creates a copy.

---

## 3. The Golden Rules of Output Formats

Connie's Uploader supports three major syntax families: **BBCode**, **Markdown**, and **HTML**.

> [!WARNING]
> **Never mix formatting syntaxes!**
> Do not put HTML tags (`<b>`) inside a BBCode template (`[b]`), and do not put BBCode tags (`[url]`) inside a Markdown template (`[text](url)`). Forums and websites only understand one language at a time.

### Syntax Cheat Sheet

| Styling Goal | BBCode (Forums, ViperGirls) | Markdown (Reddit, GitHub) | HTML (Webpages, Blogs) |
| :--- | :--- | :--- | :--- |
| **Bold** | `[b]Text[/b]` | `**Text**` | `<b>Text</b>` |
| **Italics** | `[i]Text[/i]` | `*Text*` | `<i>Text</i>` |
| **Underline** | `[u]Text[/u]` | *(Not standard)* | `<u>Text</u>` |
| **Text Color** | `[color=#FF0000]Red[/color]` | *(Not standard)* | `<span style="color:#FF0000">Red</span>` |
| **Clickable Link** | `[url=https://site.com]Link[/url]` | `[Link](https://site.com)` | `<a href="https://site.com">Link</a>` |
| **Direct Image** | `[img]https://site.com/pic.jpg[/img]` | `![](https://site.com/pic.jpg)` | `<img src="https://site.com/pic.jpg">` |
| **Clickable Thumbnail** | `[url=VIEWER][img]THUMB[/img][/url]` | `[![Alt](THUMB)](VIEWER)` | `<a href="VIEWER"><img src="THUMB"></a>` |

### How Format Resolution Works

Connie's Uploader knows which format to use based on the template's category:
* **BBCode, Forum, ViperGirls** &rarr; Output engine generates BBCode.
* **Markdown** &rarr; Output engine generates Markdown.
* **HTML** &rarr; Output engine generates HTML.
* **Custom Templates** &rarr; If the template contains HTML tags like `<html>` or `<a href`, it resolves to HTML. If the name contains `Markdown`, it resolves to Markdown. Otherwise, it defaults to BBCode.

---

## 4. Placeholders & Variables Reference

Placeholders must always be wrapped in `#` hashes (e.g. `#batch_name#`).

### 1. Media & Bulk Image Placeholders

Use these when you want the app to handle all image formatting automatically:

| Placeholder | Description | Example Output |
| :--- | :--- | :--- |
| `#all_images#` | All images (excluding selected covers) formatted as clickable thumbnails according to the output format. | `[url=...][img]...[/img][/url] [url=...][img]...[/img][/url]` |
| `#all_full_images#` | All images formatted as full direct embeds (using direct URLs). | `[img]https://.../1.jpg[/img] [img]https://.../2.jpg[/img]` |
| `#cover_images#` | All selected cover images formatted as clickable thumbnails. If 2 covers are selected, renders 2 covers. | `[url=...][img]...[/img][/url]` |
| `#cover_image#` | Clickable thumbnail for the **first** cover image (or first image in batch if none selected). | `[url=...][img]...[/img][/url]` |
| `#cover_url#` | The raw thumbnail URL string of the first cover image (useful inside custom `[url]` blocks). | `https://pixhost.cc/thumbs/1/cover.jpg` |
| `#cover_count#` | Number of cover images currently selected. | `2` |
| `#image_count#` | Total count of uploaded images in this batch. | `24` |
| `#thumb_size#` | Host thumbnail resolution setting. | `180` |

### 2. Single-Image & Loop Placeholders

> [!CAUTION]
> **Where you put these matters!**
> * **Inside a loop (`[for image]` or `[for cover]`)**: These variables represent the **current image** being processed during that pass of the loop.
> * **Outside a loop**: These variables always refer to the **first image** in the batch.

| Placeholder | Description | Example Output |
| :--- | :--- | :--- |
| `#thumb_url#` | The thumbnail image link. | `https://img.pixhost.cc/thumbs/42/image.jpg` |
| `#image_url#` | The host viewer web page link. | `https://pixhost.cc/show/42/image.html` |
| `#direct_url#` | The direct full-resolution image link (when provided by the host). | `https://img.pixhost.cc/images/42/image.jpg` |

### 3. Batch & Gallery Placeholders

| Placeholder | Description | Example Output |
| :--- | :--- | :--- |
| `#batch_name#` | Title of the batch or folder name. | `Summer Vacation 2026` |
| `#folder_size#` | Total human-readable size of all valid files in the batch. | `714 KB`, `114 MB`, or `1.34 GB` |
| `#upload_date#` | Date when the output was generated. | `2026-09-06` |
| `#service#` | Name or domain of the upload host. | `pixhost.cc` |
| `#gallery_link#` | Full URL to the remote gallery (if a gallery was created or selected). | `https://pixhost.cc/gallery/ABCDE` |
| `#gallery_name#` | Name of the remote gallery. | `My Vacation Set` |
| `#gallery_id#` | Remote host gallery ID or hash. | `ABCDE` |

### 4. ViperGirls Forum Placeholders

| Placeholder | Description | Example Output |
| :--- | :--- | :--- |
| `#thread_name#` | Name of the selected ViperGirls target thread. | `Celebrity Sets - Batch Thread` |
| `#thread_id#` | Thread ID number on the ViperGirls forum. | `458291` |

---

## 5. Working with Loops (`[for image]` & `[for cover]`)

Loops are the secret weapon of Connie's Uploader. Use loops when `#all_images#` doesn't give you enough control over layout, spacing, or embedding style.

### The Mental Model

Think of a loop like a rubber stamp:
1. Connie's Uploader takes the template inside your loop.
2. It grabs the first image, fills in `#image_url#` and `#thumb_url#`, and prints it.
3. It inserts your chosen **separator** (like a newline, a space, or a blank line).
4. It grabs the next image and repeats until all images are printed.

```
[for image separator=newline]
[url=#image_url#][img]#thumb_url#[/img][/url]
[/for]
```

### The Two Loop Types

1. **`[for image]`**: Loops over all regular images in the batch. If you selected covers, those covers are automatically set aside so they are **not** repeated in `[for image]`.
2. **`[for cover]`**: Loops exclusively over your selected cover images.

### The Separator Argument (`separator=...`)

The separator tells the app what to place between each image pass.

| Parameter | What it Inserts | Best Used For |
| :--- | :--- | :--- |
| `separator=newline` | Single line break (`\n`) | Vertical image lists, one thumbnail per line. |
| `separator=blankline` | Double line break (`\n\n`) | Full-resolution image scrolls (comfortable gap between big photos). |
| `separator=space` | Single space (`" "`) | Dense thumbnail grids that wrap naturally across the forum screen. |
| `separator=none` | No separator (`""`) | Edge-to-edge images without any gaps. |
| `separator=comma` | A comma and space (`, `) | Plain URL lists or links. |
| `separator=" - "` | Custom characters in quotes | Custom dividers (e.g. `separator=" | "` or `separator="\n---\n"`). |

> [!NOTE]
> You can also use the shorthand `sep=` instead of `separator=` (e.g. `[for image sep=space]`).

---

### Loop Examples Explained Line-by-Line

#### Example A: Dense Thumbnail Grid (Space-Separated)

```bbcode
[center]
[for image separator=space][url=#image_url#][img]#thumb_url#[/img][/url][/for]
[/center]
```

* **Line 1:** Centers the entire gallery on forum posts.
* **Line 2:** `[for image separator=space]` begins the loop. For each image, it creates a clickable thumbnail link `[url=#image_url#][img]#thumb_url#[/img][/url]`. Between each thumbnail, it inserts a single space.
* **Line 3:** `[/center]` closes the centered container.

#### Example B: Full-Resolution Image Scroll (Blank-Line Separated)

```bbcode
[center]
[b]#batch_name#[/b]

[for image separator=blankline]
[img]#direct_url#[/img]
[/for]
[/center]
```

* Shows `#batch_name#` in bold at the top.
* Each image is embedded directly using its full resolution (`#direct_url#`).
* `separator=blankline` ensures there is a clean, readable empty line between every full-size photo.

#### Example C: Separate Covers Section + Regular Images Grid

```bbcode
[center]
[b]Covers:[/b]
[for cover separator=space]
[url=#image_url#][img]#thumb_url#[/img][/url]
[/for]

[b]Gallery Set:[/b]
[for image separator=space]
[url=#image_url#][img]#thumb_url#[/img][/url]
[/for]
[/center]
```

* `[for cover]` displays only the images you marked as covers.
* `[for image]` displays all the remaining images. Neither section duplicates the other!

---

## 6. Working with Conditionals (`[if]` & `[else]`)

Conditionals allow you to write smart templates that show certain sections **only when that data exists**.

### Basic Truthiness Check

```bbcode
[if placeholder_name]
... this shows only if placeholder_name has a value ...
[/if]
```

* If the variable has text (like a URL, batch name, or size), the content inside is included.
* If the variable is empty or blank, everything between `[if]` and `[/if]` is completely omitted.

> [!TIP]
> The condition tag takes the variable name **without** hashes: use `[if gallery_link]` rather than `[if #gallery_link#]`. (Both work, but without hashes is cleaner).

### Adding an `[else]` Branch

```bbcode
[if gallery_link]
[url=#gallery_link#]Open Full Gallery[/url]
[else]
(No remote gallery created)
[/if]
```

### Exact Value Matching

You can also test if a placeholder matches a specific value:

```text
[if service="pixhost.cc"]Uploaded to Pixhost![/if]
[if image_count=1]Single Photo Batch[else]Multi Photo Batch[/if]
```

### Nesting Conditionals

You can nest conditionals inside each other or inside loops:

```bbcode
[if gallery_link]
[url=#gallery_link#]View Gallery[/url]
[if folder_size] (#folder_size#)[/if]
[/if]
```

---

## 7. Copy & Paste Recipes

Copy any of these recipes directly into your Template Editor (**Save As New...**)!

### Recipe 1: Professional ViperGirls Forum Post (Recommended)

Includes batch title, optional gallery link, folder size, cover section, and dense thumbnail grid:

```bbcode
[center][b]#batch_name#[/b]
[if folder_size][size=2]Total Size: #folder_size#[/size]
[/if][if gallery_link][url=#gallery_link#][b]📂 Open Full Gallery[/b][/url]
[/if][if thread_name][size=1]Target Thread: #thread_name#[/size]
[/if]
#cover_images#

[for image separator=space][url=#image_url#][img]#thumb_url#[/img][/url][/for][/center]
```

### Recipe 2: Full-Resolution Image Scroll (Direct Images)

Best for blogs, full image forums, or direct display without thumbnails:

```bbcode
[center][b]#batch_name#[/b] [if folder_size](#folder_size#)[/if]

[for image separator=blankline][img]#direct_url#[/img][/for]

[if gallery_link][url=#gallery_link#]View Complete Gallery[/url][/if][/center]
```

### Recipe 3: Reddit / Markdown Post

Outputs clean Markdown with linked thumbnails and an optional gallery header:

```markdown
[if gallery_link][**📂 View Gallery (#gallery_name#)**](#gallery_link#)[if folder_size] - *#folder_size#*[/if]

[/if][for image separator=space][![#batch_name#](#thumb_url#)](#image_url#)[/for]
```

### Recipe 4: Clean Standalone HTML Page

Outputs a complete HTML page wrapper with responsive grid:

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>#batch_name#</title>
  <style>
    body { font-family: sans-serif; text-align: center; background: #1e1e1e; color: #fff; padding: 20px; }
    .grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin-top: 20px; }
    img { border-radius: 4px; border: 1px solid #444; }
  </style>
</head>
<body>
  <h2>#batch_name#</h2>
  [if folder_size]<p>Size: #folder_size# | Images: #image_count#</p>[/if]
  [if gallery_link]<p><a href="#gallery_link#" style="color: #4da6ff;">View Remote Gallery</a></p>[/if]
  <div class="grid">
    [for image separator=newline]<a href="#image_url#"><img src="#thumb_url#"></a>[/for]
  </div>
</body>
</html>
```

---

## 8. Common Pitfalls & Troubleshooting Checklist

If your template doesn't produce the output you expect, consult this checklist:

### 1. "Template has an unclosed `[for image]` block"
* **Cause**: You typed `[for image]` but forgot to close it with `[/for]`.
* **Fix**: Ensure every `[for image]` and `[for cover]` has a corresponding `[/for]`.

### 2. "Template has an unclosed `[if]` block"
* **Cause**: You started an `[if ...]` statement but didn't close it with `[/if]`.
* **Fix**: Check your conditionals and make sure all opened `[if]` tags have `[/if]`.

### 3. My images duplicated 20 times!
* **Cause**: You put `#all_images#` **inside** a `[for image]` loop:
  ```bbcode
  <!-- WRONG: DO NOT DO THIS -->
  [for image separator=space]
  #all_images#
  [/for]
  ```
* **Fix**: Inside a loop, use the single-image placeholder `#thumb_url#` and `#image_url#`. Do not use `#all_images#` inside a loop!

### 4. Broken image icons appear on the forum
* **Cause**: You used `#image_url#` instead of `#direct_url#` or `#thumb_url#` inside `[img]`:
  ```bbcode
  <!-- WRONG: #image_url# is a webpage link, not an image file -->
  [img]#image_url#[/img]

  <!-- CORRECT: -->
  [url=#image_url#][img]#thumb_url#[/img][/url]
  <!-- OR for full size: -->
  [img]#direct_url#[/img]
  ```

### 5. My cover image is missing from the bottom list
* **Behavior**: This is intentional! Connie's Uploader automatically excludes selected cover images from `#all_images#` and `[for image]` so that your cover photo isn't awkwardly repeated twice.
* **Fix**: Place `#cover_images#` or `[for cover]` at the top of your template to showcase the covers.

### 6. "Template must contain at least one image placeholder"
* **Cause**: Templates must actually output images. If you create a template with only text or batch metadata, Connie's Uploader blocks it from saving.
* **Fix**: Include at least one image marker (`#all_images#`, `#all_full_images#`, `#cover_images#`, `#cover_image#`, `[for image]`, or `[for cover]`).

### 7. Preview button doesn't do anything or shows empty data
* **Cause**: The upload queue in the main Connie's Uploader window is empty.
* **Fix**: Add at least one image or folder to the main window before clicking **Preview in Browser** or **Copy Preview Output**.
