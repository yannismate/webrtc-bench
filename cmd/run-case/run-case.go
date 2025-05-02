package main

import (
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"os"
	"webrtc-bench/internal/cases"
)

func main() {
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stdout})

	caseInstance := cases.CaseConnectChrome{}
	err := caseInstance.Configure(cases.PeerCaseConfig{
		Implementation:   "chrome",
		ICEServers:       []string{"stun:stun.l.google.com:19302"},
		SendOffer:        true,
		StatInterval:     100,
		AdditionalConfig: nil,
	}, func(signalType cases.PeerSignalType, data []byte) error {
		return nil
	}, nil)

	if err != nil {
		log.Fatal().Err(err).Msgf("error configuring chrome")
		return
	}

	log.Info().Msg("Configuration finished")

	err = caseInstance.Start()
	if err != nil {
		log.Fatal().Err(err).Msgf("error starting case")
		return
	}

	select {}
}
