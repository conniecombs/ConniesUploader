// SPDX-License-Identifier: MIT
// Copyright (c) 2025 conniecombs

package main

import (
	"fmt"

	"github.com/conniecombs/GolangVersion/services"
	"github.com/conniecombs/GolangVersion/services/imx"
	"github.com/conniecombs/GolangVersion/services/pixhost"
	"github.com/conniecombs/GolangVersion/services/vipr"
)

func createPixhostGallery(name string) (map[string]string, error) {
	ensureInitialized()
	svc, ok := registry.Get(pixhost.ServiceID)
	if !ok {
		return nil, fmt.Errorf("pixhost module not registered")
	}
	creator, ok := svc.(services.GalleryCreator)
	if !ok {
		return nil, fmt.Errorf("pixhost does not implement GalleryCreator")
	}
	_, data, err := creator.CreateGallery(nil, name)
	if err != nil {
		return nil, err
	}
	if m, ok := data.(map[string]string); ok {
		return m, nil
	}
	return nil, fmt.Errorf("unexpected data type from pixhost.CreateGallery")
}

func createImxGallery(creds map[string]string, name string) (string, error) {
	ensureInitialized()
	svc, ok := registry.Get(imx.ServiceID)
	if !ok {
		return "", fmt.Errorf("imx module not registered")
	}
	creator, ok := svc.(services.GalleryCreator)
	if !ok {
		return "", fmt.Errorf("imx does not implement GalleryCreator")
	}
	id, _, err := creator.CreateGallery(creds, name)
	return id, err
}

func createViprGallery(name string) (string, error) {
	ensureInitialized()
	svc, ok := registry.Get(vipr.ServiceID)
	if !ok {
		return "", fmt.Errorf("vipr module not registered")
	}
	creator, ok := svc.(services.GalleryCreator)
	if !ok {
		return "", fmt.Errorf("vipr does not implement GalleryCreator")
	}
	id, _, err := creator.CreateGallery(nil, name)
	return id, err
}
