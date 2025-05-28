package util

import "github.com/rs/zerolog/log"

func AssumeNoErr[K any](val K, err error) K {
	if err != nil {
		log.Fatal().Err(err).Msg("Assumed no error, but got error!")
	}
	return val
}
