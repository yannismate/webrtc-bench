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
	zerolog.SetGlobalLevel(zerolog.InfoLevel)

	clientName := flag.String("name", "", "Client name")
	verbose := flag.Bool("v", false, "enable verbose mode")
	authenticationKey := flag.String("authenticationKey", "default-auth-key", "Authentication key")
	serverAddress := flag.String("server", "127.0.0.1:8080", "Server address")

	flag.Parse()

	if *verbose {
		zerolog.SetGlobalLevel(zerolog.DebugLevel)
	}

	if *authenticationKey == "default-auth-key" {
		log.Warn().Msg("Authentication key set to default!")
	}

	if clientName == nil || *clientName == "" {
		log.Fatal().Msg("You must specify a client name")
		return
	}

	log.Info().Msgf("Starting Client %s", *clientName)

	client := management.NewClient(*serverAddress, *clientName, *authenticationKey)
	client.Start()

	c := make(chan os.Signal, 1)
	signal.Notify(c, os.Interrupt)

	select {
	case <-c:
	}
	client.Stop()
	log.Info().Msg("Exiting!")
}
