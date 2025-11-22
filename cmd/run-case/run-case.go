package main

import (
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"os"
	"time"
	"webrtc-bench/internal/cases"
)

func main() {
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stdout})

	os.Setenv("TEAMS_AUTH_PATH", "C:\\Users\\yanni\\go\\src\\webrtc-bench\\teams_credentials.json")
	caseInstance := cases.CaseVideoTeams{}
	err := caseInstance.Configure(cases.PeerCaseConfig{
		Implementation: "teams",
		ICEServers:     []string{},
		SendOffer:      false,
		StatInterval:   100,
		AdditionalConfig: map[string]string{
			"meeting_url": "https://teams.live.com/meet/9345053427608?p=q2RtCHzbzPPAYFxfrW",
			"headless":    "false",
		},
	}, func(signalType cases.PeerSignalType, data []byte) error {
		return nil
	}, nil)

	if err != nil {
		log.Fatal().Err(err).Msgf("error configuring chrome")
		return
	}

	log.Info().Msg("Configuration finished")

	time.Sleep(time.Duration(15) * time.Minute)

	err = caseInstance.Start()
	if err != nil {
		log.Fatal().Err(err).Msgf("error starting case")
		return
	}

	select {}
}
