package cases

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"github.com/chromedp/cdproto/page"
	"github.com/chromedp/cdproto/webauthn"
	"github.com/chromedp/chromedp/kb"
	"io"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"time"
	"webrtc-bench/internal/cases/stats"
	"webrtc-bench/internal/results"
	"webrtc-bench/internal/util"

	"github.com/chromedp/chromedp"
	"github.com/rs/zerolog/log"
)

type CaseVideoTeams struct {
	browserContext       context.Context
	browserContextCancel context.CancelFunc
	statCollector        stats.StatCollector
	meetingUrl           string
	teamsCredential      *teamsCredentialData
	statInterval         time.Duration
}

type teamsCredentialData struct {
	Email        string `json:"email"`
	CredentialId string `json:"credentialId"`
	PrivateKey   string `json:"privateKey"`
	UserHandle   string `json:"userHandle"`
	SignCount    int64  `json:"signCount"`
}

//go:embed teams_video.js
var caseTeamsVideoJs string

//go:embed teams_video_prefs.json
var caseTeamsVideoChromePrefs string

//go:embed teams_video_proxy_patch.js
var caseTeamsVideoRTCProxyJs string

const (
	TeamsLoginUrl = "https://teams.microsoft.com/v2/"
)

func (c *CaseVideoTeams) Configure(config PeerCaseConfig, sendSignal func(signalType PeerSignalType, data []byte) error, statCollector stats.StatCollector) error {
	c.browserContext, c.browserContextCancel = chromedp.NewContext(context.Background())
	c.statCollector = statCollector

	cwd, err := os.Getwd()
	if err != nil {
		return err
	}

	videoFilePath, ok := config.AdditionalConfig["video_file"]
	if !ok {
		videoFilePath = path.Join(cwd, "testdata", "test.y4m")
	}

	if meetingUrl, ok := config.AdditionalConfig["meeting_url"]; ok {
		c.meetingUrl = meetingUrl
	} else {
		return errors.New("meeting url not found in config")
	}

	headless := true
	if val, ok := config.AdditionalConfig["headless"]; ok && val == "false" {
		headless = false
	}

	c.statInterval = time.Duration(config.StatInterval)

	if !config.SendOffer {
		// Read teams credentials from json file:
		authPath := os.Getenv("TEAMS_AUTH_PATH")
		if authPath == "" {
			return errors.New("TEAMS_AUTH_PATH not found in environment")
		}
		file, err := os.Open(authPath)
		if err != nil {
			return err
		}

		defer file.Close()
		fileBytes, err := io.ReadAll(file)
		if err != nil {
			return err
		}

		err = json.Unmarshal(fileBytes, &c.teamsCredential)
		if err != nil {
			return err
		}
		if c.teamsCredential.Email == "" {
			return errors.New("email not found in teams credential")
		}
		log.Info().Msgf("Loaded teams credentials for email %v", c.teamsCredential.Email)
	}

	log.Debug().Msgf("Using video source from %s", videoFilePath)

	prefsTempDir, err := os.MkdirTemp("", "chromedp-prefs")
	if err != nil {
		return err
	}
	log.Debug().Msgf("Using prefs temp dir %v", prefsTempDir)

	if err := os.Mkdir(filepath.Join(prefsTempDir, "Default"), 0o700); err != nil {
		return err
	}

	if err := os.WriteFile(filepath.Join(prefsTempDir, "Default", "Preferences"), []byte(caseTeamsVideoChromePrefs), 0o600); err != nil {
		return err
	}

	opts := append(chromedp.DefaultExecAllocatorOptions[:],
		chromedp.Flag("headless", headless),
		chromedp.UserDataDir(prefsTempDir),
		chromedp.Flag("disable-notifications", true),
		chromedp.Flag("disable-gesture-requirement-for-media-playback", true),
		chromedp.Flag("use-fake-ui-for-media-stream", true),
		chromedp.Flag("use-fake-device-for-media-stream", true),
		chromedp.Flag("use-file-for-fake-video-capture", videoFilePath),
	)

	parentCtx, parentCtxCancel := chromedp.NewExecAllocator(context.Background(), opts...)
	browserContext, browserContextCancel := chromedp.NewContext(parentCtx)

	c.browserContext = browserContext
	c.browserContextCancel = func() {
		browserContextCancel()
		parentCtxCancel()
		_ = os.RemoveAll(prefsTempDir)
	}

	// Automatically inject RTCPeerConnection proxy constructor on page load
	chromedp.ListenTarget(c.browserContext, func(ev interface{}) {
		switch ev.(type) {
		case *page.EventFrameNavigated:
			// A frame (including main frame) just navigated — inject the script
			go func() {
				_ = chromedp.Run(c.browserContext, chromedp.Evaluate(caseTeamsVideoRTCProxyJs, nil))
			}()
		}
	})

	if config.SendOffer {
		err := c.SetupTeamsSender()
		if err != nil {
			log.Error().Err(err).Msg("Error setting up teams sender")
			return err
		}
	} else {
		err := c.SetupTeamsReceiver()
		if err != nil {
			log.Error().Err(err).Msg("Error setting up teams receiver")
			return err
		}
	}

	return nil
}

func (c *CaseVideoTeams) SetupTeamsReceiver() error {
	log.Debug().Msg("Setting up teams meeting receiver...")

	timeoutContext, cancel := context.WithTimeout(c.browserContext, time.Duration(1)*time.Minute)
	defer cancel()

	var authId webauthn.AuthenticatorID

	err := chromedp.Run(timeoutContext,
		chromedp.Navigate(TeamsLoginUrl),
		chromedp.WaitVisible("input[name=\"loginfmt\"]"))
	if err != nil {
		return err
	}

	err = chromedp.Run(timeoutContext,
		webauthn.Enable(),
		chromedp.ActionFunc(func(ctx context.Context) error {
			aid, err := webauthn.AddVirtualAuthenticator(&webauthn.VirtualAuthenticatorOptions{
				Protocol:                    webauthn.AuthenticatorProtocolCtap2,
				Transport:                   webauthn.AuthenticatorTransportUsb,
				Ctap2version:                webauthn.Ctap2versionCtap21,
				HasResidentKey:              true,
				HasUserVerification:         true,
				HasLargeBlob:                true,
				AutomaticPresenceSimulation: true,
				IsUserVerified:              true,
			}).Do(ctx)
			log.Debug().Msgf("Added virtual authenticator with id %s", aid)
			authId = aid
			return err
		}))
	if err != nil {
		return err
	}

	err = chromedp.Run(timeoutContext,
		webauthn.SetAutomaticPresenceSimulation(authId, true),
		webauthn.AddCredential(authId, &webauthn.Credential{
			CredentialID:         c.teamsCredential.CredentialId,
			IsResidentCredential: true,
			RpID:                 "login.microsoft.com",
			PrivateKey:           c.teamsCredential.PrivateKey,
			UserHandle:           c.teamsCredential.UserHandle,
			SignCount:            c.teamsCredential.SignCount,
		}))
	if err != nil {
		return err
	}
	log.Debug().Msg("Set up emulated credential...")

	err = chromedp.Run(timeoutContext,
		chromedp.SendKeys("input[name=\"loginfmt\"]", c.teamsCredential.Email),
		chromedp.SendKeys("input[name=\"loginfmt\"]", kb.Enter),
		chromedp.Sleep(5*time.Second),
		chromedp.WaitVisible("button[type=submit]"),
		chromedp.Click("button[type=submit]"),
		chromedp.WaitVisible("#idna-me-control-avatar-trigger"))

	log.Debug().Msg("Teams sign-in succeeded!")

	err = chromedp.Run(timeoutContext,
		chromedp.ActionFunc(func(ctx context.Context) error {
			creds, err := webauthn.GetCredentials(authId).Do(ctx)
			if err == nil {
				newSignCount := creds[0].SignCount
				log.Info().Msgf("New sign count: %v", newSignCount)
				c.teamsCredential.SignCount = newSignCount

				updatedJsonBytes, err := json.MarshalIndent(c.teamsCredential, "", "  ")
				if err != nil {
					log.Fatal().Err(err).Msg("failed to marshal updated teams credentials")
				}
				file, err := os.Create(os.Getenv("TEAMS_AUTH_PATH"))
				if err != nil {
					log.Fatal().Err(err).Msg("failed to create updated file at TEAMS_AUTH_PATH")
				}
				defer file.Close()
				_, err = file.Write(updatedJsonBytes)
				if err != nil {
					log.Fatal().Err(err).Msg("failed to write updated teams credentials to file")
				}
			}
			return err
		}))

	err = chromedp.Run(timeoutContext,
		chromedp.Navigate(c.meetingUrl),
		chromedp.WaitVisible("button[data-tid=\"joinOnWeb\"]"),
		chromedp.Click("button[data-tid=\"joinOnWeb\"]"),
		chromedp.WaitVisible("#prejoin-join-button"),
		chromedp.Click("#prejoin-join-button"))

	if err != nil {
		return err
	}
	log.Debug().Msg("Joined meeting.")

	err = chromedp.Run(timeoutContext,
		chromedp.WaitVisible("div[data-tid=\"voice-level-stream-outline\"]"))

	if err != nil {
		return err
	}
	log.Debug().Msg("Sender connected!")

	return nil
}

func (c *CaseVideoTeams) SetupTeamsSender() error {
	log.Debug().Msg("Setting up teams meeting sender...")

	timeoutContext, cancel := context.WithTimeout(c.browserContext, time.Duration(1)*time.Minute)
	defer cancel()

	err := chromedp.Run(timeoutContext,
		chromedp.Navigate(c.meetingUrl),
		chromedp.WaitVisible("button[data-tid=\"joinOnWeb\"]"),
		chromedp.Click("button[data-tid=\"joinOnWeb\"]"),
		chromedp.WaitVisible("input[data-tid=\"prejoin-display-name-input\""),
		chromedp.SendKeys("input[data-tid=\"prejoin-display-name-input\"", "TestSender"),
		chromedp.WaitVisible("#prejoin-join-button"),
		chromedp.Click("#prejoin-join-button"))
	if err != nil {
		return err
	}

	log.Debug().Msg("Joined meeting as sender.")

	err = chromedp.Run(timeoutContext,
		chromedp.WaitVisible("div[data-tid=\"voice-level-stream-outline\"]"))
	if err != nil {
		return err
	}
	log.Debug().Msg("Receiver connected!")

	return nil
}

func (c *CaseVideoTeams) browserMessage(msgText string) {
	var msg browserMessage
	err := json.Unmarshal([]byte(msgText), &msg)
	if err != nil {
		log.Error().Err(err).Str("msg", msgText).Msg("Error unmarshalling browser message")
		return
	}

	switch msg.Type {
	case "log":
		log.Info().Msgf("[Chrome] %s", msg.Value)
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

func (c *CaseVideoTeams) Start() error {
	setParamsJs := "const STAT_INTERVAL_MS = " + strconv.FormatInt(c.statInterval.Milliseconds(), 10) + ";\n"

	var res []string

	err := chromedp.Run(c.browserContext,
		util.ExposeFunc("sendManagementMessage", c.browserMessage),
		chromedp.EvaluateAsDevTools(setParamsJs+caseTeamsVideoJs, &res, chromedp.EvalWithCommandLineAPI))

	if err != nil {
		return err
	}
	return nil
}

func (c *CaseVideoTeams) OnReceiveSignal(signalType PeerSignalType, message []byte) error {
	// Signalling is done through teams
	log.Error().Msg("OnReceiveSignal received signal even though teams cases do not accept signals.")
	return nil
}

func (c *CaseVideoTeams) GetLargeResultFiles() *map[string]string {
	return nil
}

func (c *CaseVideoTeams) GetExtraResultFiles() *map[string][]byte {
	return nil
}

func (c *CaseVideoTeams) Stop() {
	c.statCollector.StopCollection()
	c.browserContextCancel()
}
