package util

import (
	"os"
	"runtime/debug"
	"time"
)

const (
	pionImportPath = "github.com/pion/webrtc/v4"
)

type TestMetadata struct {
	ImplementationType    string    `json:"implementation_type"`
	ImplementationVersion string    `json:"implementation_version"`
	TimeStarted           time.Time `json:"time_started"`
	Host                  string    `json:"host"`
}

func GetTestMetadata() TestMetadata {
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
	}
}
