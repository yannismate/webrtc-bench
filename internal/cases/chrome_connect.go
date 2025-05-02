package cases

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"github.com/chromedp/cdproto/runtime"
	"github.com/chromedp/chromedp"
	"github.com/rs/zerolog/log"
	"strconv"
	"strings"
	"sync"
	"webrtc-bench/internal/cases/stats"
	"webrtc-bench/internal/util"
)

type CaseConnectChrome struct {
	browserContext       context.Context
	browserContextCancel context.CancelFunc
	sendSignal           func(signalType PeerSignalType, data []byte) error
	chromeSignalMutex    sync.Mutex
}

//go:embed chrome_connect.js
var caseJs string

func (c *CaseConnectChrome) Configure(config PeerCaseConfig, sendSignal func(signalType PeerSignalType, data []byte) error, statCollector stats.StatCollector) error {
	c.browserContext, c.browserContextCancel = chromedp.NewContext(context.Background())
	c.sendSignal = sendSignal

	setParamsJs := "const ICE_SERVERS = [\"" + strings.Join(config.ICEServers, "\", \"") + "\"];\n"
	setParamsJs += "const DO_OFFER = " + strconv.FormatBool(config.SendOffer) + ";"

	var res []string
	err := chromedp.Run(c.browserContext,
		chromedp.Navigate("about:blank"),
		util.ExposeFunc("sendManagementMessage", c.browserMessage),
		chromedp.EvaluateAsDevTools(setParamsJs, &res),
		chromedp.EvaluateAsDevTools(caseJs, &res))
	if err != nil {
		return err
	}

	return nil
}

type browserMessage struct {
	Type  string `json:"type"`
	Value string `json:"value"`
}

func (c *CaseConnectChrome) browserMessage(msgText string) {
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
	}
}

func (c *CaseConnectChrome) Start() error {
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

func (c *CaseConnectChrome) OnReceiveSignal(signalType PeerSignalType, message []byte) error {
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

func (c *CaseConnectChrome) Stop() {
	var res []string
	err := chromedp.Run(c.browserContext,
		chromedp.EvaluateAsDevTools("stop();", &res, func(params *runtime.EvaluateParams) *runtime.EvaluateParams {
			return params.WithAwaitPromise(true)
		}))
	if err != nil {
		log.Warn().Err(err).Msg("Failed to stop case in Chrome")
	}

	c.browserContextCancel()
}
