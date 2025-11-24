package main

import (
	"flag"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"net"
	"os"
	"os/signal"
	"runtime"
	"strings"
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

	if runtime.GOOS == "linux" {
		// Log current resolv.conf if on linux
		resolvConfData, err := os.ReadFile("/etc/resolv.conf")
		if err != nil {
			log.Warn().Err(err).Msg("Could not read /etc/resolv.conf")
		} else {
			log.Info().Msgf("Current /etc/resolv.conf:")
			for line := range strings.Lines(string(resolvConfData)) {
				log.Info().Msgf("  %s", strings.TrimRight(line, "\r\n"))
			}
			log.Info().Msgf("EOF")
		}

		// Check if teams domain is resolvable
		ips, err := net.LookupIP("teams.live.com")
		if err != nil || len(ips) == 0 {
			log.Warn().Err(err).Msgf("MS Teams domain is not resolvable!")
		} else {
			log.Info().Msgf("MS Teams domain is resolvable, first IP: %v", ips[0].String())
		}
	}

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
