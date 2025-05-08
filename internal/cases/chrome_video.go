package cases

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"github.com/chromedp/cdproto/runtime"
	"github.com/chromedp/chromedp"
	"github.com/rs/zerolog/log"
	"os"
	"path"
	"strconv"
	"strings"
	"sync"
	"time"
	"webrtc-bench/internal/cases/stats"
	"webrtc-bench/internal/results"
	"webrtc-bench/internal/util"
)

type CaseVideoChrome struct {
	browserContext       context.Context
	browserContextCancel context.CancelFunc
	sendSignal           func(signalType PeerSignalType, data []byte) error
	chromeSignalMutex    sync.Mutex
	statCollector        stats.StatCollector
}

//go:embed chrome_video.js
var caseVideoJs string

func (c *CaseVideoChrome) Configure(config PeerCaseConfig, sendSignal func(signalType PeerSignalType, data []byte) error, statCollector stats.StatCollector) error {
	c.browserContext, c.browserContextCancel = chromedp.NewContext(context.Background())
	c.sendSignal = sendSignal
	c.statCollector = statCollector

	cwd, err := os.Getwd()
	if err != nil {
		return err
	}

	videoFilePath, ok := config.AdditionalConfig["video_file"]
	if !ok {
		videoFilePath = path.Join("testdata", "test.y4m")
	}

	opts := append(chromedp.DefaultExecAllocatorOptions[:],
		chromedp.Flag("allow-file-access-from-files", "true"),
		chromedp.Flag("disable-gesture-requirement-for-media-playback", "true"),
		chromedp.Flag("use-fake-ui-for-media-stream", "true"),
		chromedp.Flag("use-fake-device-for-media-stream", "true"),
		chromedp.Flag("use-file-for-fake-video-capture", path.Join(cwd, videoFilePath)),
	)

	parentCtx, parentCtxCancel := chromedp.NewExecAllocator(context.Background(), opts...)
	browserContext, browserContextCancel := chromedp.NewContext(parentCtx)

	c.browserContext = browserContext
	c.browserContextCancel = func() {
		browserContextCancel()
		parentCtxCancel()
	}

	setParamsJs := "const ICE_SERVERS = [\"" + strings.Join(config.ICEServers, "\", \"") + "\"];\n"
	setParamsJs += "const DO_OFFER = " + strconv.FormatBool(config.SendOffer) + ";\n"
	setParamsJs += "const STAT_INTERVAL_MS = " + strconv.FormatInt(time.Duration(config.StatInterval).Milliseconds(), 10) + ";"

	var res []string
	err = chromedp.Run(c.browserContext,
		chromedp.Navigate("file://"+path.Join(cwd, "testdata", "empty_page.html")),
		util.ExposeFunc("sendManagementMessage", c.browserMessage),
		chromedp.EvaluateAsDevTools(setParamsJs, &res),
		chromedp.EvaluateAsDevTools(caseVideoJs, &res))
	if err != nil {
		return err
	}

	return nil
}

func (c *CaseVideoChrome) browserMessage(msgText string) {
	var msg browserMessage
	err := json.Unmarshal([]byte(msgText), &msg)
	if err != nil {
		log.Error().Err(err).Str("msg", msgText).Msg("Error unmarshalling browser message")
		return
	}

	switch msg.Type {
	case "log":
		log.Info().Msgf("[Chrome] %s", msg.Value)
	case "sdp":
		err := c.sendSignal(PeerSignalTypeSDP, []byte(msg.Value))
		if err != nil {
			log.Error().Err(err).Str("msg", msg.Value).Msg("Error sending signal")
			return
		}
	case "candidates":
		err := c.sendSignal(PeerSignalTypeCandidates, []byte(msg.Value))
		if err != nil {
			log.Error().Err(err).Str("msg", msg.Value).Msg("Error sending signal")
			return
		}
	case "stats":
		var statLine results.ResultRow
		err := json.Unmarshal([]byte(msg.Value), &statLine)
		if err != nil {
			log.Error().Err(err).Str("msg", msg.Value).Msg("Error unmarshalling stats")
			return
		}

		c.statCollector.RecordRow(statLine)
	}
}

func (c *CaseVideoChrome) Start() error {
	var res []string
	err := chromedp.Run(c.browserContext,
		chromedp.EvaluateAsDevTools("start();", &res, func(params *runtime.EvaluateParams) *runtime.EvaluateParams {
			return params.WithAwaitPromise(true)
		}))
	if err != nil {
		log.Error().Err(err).Msg("Failed to start case in Chrome")
		return err
	}

	return nil
}

func (c *CaseVideoChrome) OnReceiveSignal(signalType PeerSignalType, message []byte) error {
	functionCall := fmt.Sprintf("receiveManagementMessage(%q, %q);", signalType, string(message))

	c.chromeSignalMutex.Lock()
	defer c.chromeSignalMutex.Unlock()

	var res []string
	err := chromedp.Run(c.browserContext,
		chromedp.EvaluateAsDevTools(functionCall, &res, func(params *runtime.EvaluateParams) *runtime.EvaluateParams {
			return params.WithAwaitPromise(true)
		}))
	if err != nil {
		log.Error().Err(err).Msg("Failed to send signal to Chrome")
		return err
	}

	return nil
}

func (c *CaseVideoChrome) Stop() {
	var res []string
	err := chromedp.Run(c.browserContext,
		chromedp.EvaluateAsDevTools("stop();", &res, func(params *runtime.EvaluateParams) *runtime.EvaluateParams {
			return params.WithAwaitPromise(true)
		}))
	if err != nil {
		log.Warn().Err(err).Msg("Failed to stop case in Chrome")
	}

	c.statCollector.StopCollection()
	c.browserContextCancel()
}
