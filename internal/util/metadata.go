package util

import (
	"context"
	"github.com/chromedp/cdproto/browser"
	"github.com/chromedp/cdproto/cdp"
	"github.com/chromedp/chromedp"
	"github.com/rs/zerolog/log"
	"os"
	"runtime/debug"
	"time"
)

const (
	pionImportPath = "github.com/pion/webrtc/v4"
)

type TestMetadata struct {
	ImplementationType    string    `json:"implementation_type"`
	ImplementationVersion string    `json:"implementation_version"`
	TimeStarted           time.Time `json:"time_started"`
	Host                  string    `json:"host"`
}

func GetPionTestMetadata() TestMetadata {
	buildInfo, ok := debug.ReadBuildInfo()
	if !ok {
		return TestMetadata{}
	}

	pionVersion := "unknown"

	for _, dep := range buildInfo.Deps {
		if dep.Path == pionImportPath {
			pionVersion = dep.Version
		}
	}

	hostName, _ := os.Hostname()

	return TestMetadata{
		ImplementationType:    "pion",
		ImplementationVersion: pionVersion,
		TimeStarted:           time.Now(),
		Host:                  hostName,
	}
}

func GetChromeTestMetadata() TestMetadata {
	hostName, _ := os.Hostname()

	ctx, cancel := chromedp.NewContext(context.Background())
	defer cancel()

	err := chromedp.Run(ctx, chromedp.Navigate("about:blank"))
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to start browser to get version")
	}
	chromeDpContext := chromedp.FromContext(ctx)
	_, product, _, _, _, err := browser.GetVersion().Do(cdp.WithExecutor(ctx, chromeDpContext.Target))

	if err != nil {
		log.Error().Err(err).Msg("Failed to get browser version")
	}

	return TestMetadata{
		ImplementationType:    "chrome",
		ImplementationVersion: product,
		TimeStarted:           time.Now(),
		Host:                  hostName,
	}
}

func GetLibWebRTCTestMetadata() TestMetadata {
	hostName, _ := os.Hostname()

	return TestMetadata{
		ImplementationType:    "libwebrtc",
		ImplementationVersion: "TODO",
		TimeStarted:           time.Now(),
		Host:                  hostName,
	}
}
