package util

import (
	"context"
	"os"
	"runtime/debug"
	"time"

	"github.com/chromedp/cdproto/browser"
	"github.com/chromedp/cdproto/cdp"
	"github.com/chromedp/chromedp"
	"github.com/rs/zerolog/log"
)

const (
	pionImportPath = "github.com/pion/webrtc/v4"
)

type TestMetadata struct {
	ImplementationType    string    `json:"implementation_type"`
	ImplementationVersion string    `json:"implementation_version"`
	TimeStarted           time.Time `json:"time_started"`
	Host                  string    `json:"host"`
	PeerPublicIP          string    `json:"peer_public_ip"`
}

func GetPionTestMetadata(publicIP string) TestMetadata {
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
		PeerPublicIP:          publicIP,
	}
}

func GetChromeTestMetadata(publicIP string, isCustomVersion bool) TestMetadata {
	hostName, _ := os.Hostname()

	headlessShellPath := "/usr/bin/chromium-headless-shell"
	if isCustomVersion {
		headlessShellPath = "bin/headless_shell/headless_shell"
	}
	opts := append(chromedp.DefaultExecAllocatorOptions[:], chromedp.ExecPath(headlessShellPath))
	parentCtx, parentCtxCancel := chromedp.NewExecAllocator(context.Background(), opts...)
	defer parentCtxCancel()

	ctx, cancel := chromedp.NewContext(parentCtx)
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
		PeerPublicIP:          publicIP,
	}
}

func GetLibWebRTCTestMetadata(publicIP string) TestMetadata {
	hostName, _ := os.Hostname()

	return TestMetadata{
		ImplementationType:    "libwebrtc",
		ImplementationVersion: "TODO",
		TimeStarted:           time.Now(),
		Host:                  hostName,
		PeerPublicIP:          publicIP,
	}
}

func GetIPerfTestMetadata(publicIP string) TestMetadata {
	hostName, _ := os.Hostname()

	return TestMetadata{
		ImplementationType:    "iperf3",
		ImplementationVersion: "",
		TimeStarted:           time.Now(),
		Host:                  hostName,
		PeerPublicIP:          publicIP,
	}
}
