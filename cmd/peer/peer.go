package main

import (
	"flag"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"os"
	"os/signal"
	"webrtc-bench/internal/management"
)

func main() {
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stdout})
	clientName := flag.String("name", "", "Client name")
	flag.Parse()

	if clientName == nil || *clientName == "" {
		log.Fatal().Msg("You must specify a client name")
		return
	}

	log.Info().Msgf("Starting Client %s", *clientName)

	client := management.NewClient("127.0.0.1:8080", *clientName, "someAuthenticationKey")
	client.Start()

	c := make(chan os.Signal, 1)
	signal.Notify(c, os.Interrupt)

	select {
	case <-c:
	}
	client.Stop()
	log.Info().Msg("Exiting!")
}
