package cases

import (
	"encoding/json"
	"errors"
	"github.com/pion/interceptor"
	"github.com/pion/webrtc/v4"
	"github.com/rs/zerolog/log"
	"strconv"
	"sync"
	"time"
	"webrtc-bench/internal/cases/stats"
	"webrtc-bench/internal/cases/testsource"
)

type CaseVideoPion struct {
	sendSignal     func(signalType PeerSignalType, data []byte) error
	webrtcCfg      webrtc.Configuration
	sendOffer      bool
	peerConnection *webrtc.PeerConnection

	pendingCandidates []*webrtc.ICECandidate
	candidatesMux     sync.Mutex
	statCollector     stats.StatCollector
	statInterval      time.Duration
	testSource        testsource.FakeRTPDataWriter
}

func (c *CaseVideoPion) Configure(config PeerCaseConfig, sendSignal func(signalType PeerSignalType, data []byte) error, statCollector stats.StatCollector) error {
	c.sendSignal = sendSignal
	c.webrtcCfg = webrtc.Configuration{
		ICEServers: []webrtc.ICEServer{
			{
				URLs: config.ICEServers,
			},
		},
	}
	c.sendOffer = config.SendOffer
	c.statCollector = statCollector

	bitrateStr, ok := config.AdditionalConfig["bitrate"]
	if !ok {
		bitrateStr = "10000"
	}
	bitrate, err := strconv.Atoi(bitrateStr)
	if err != nil {
		return err
	}

	c.testSource = testsource.NewFakeRTPDataWriter(bitrate)
	return nil
}

func (c *CaseVideoPion) Start() error {
	mediaEngine := webrtc.MediaEngine{}
	err := mediaEngine.RegisterDefaultCodecs()
	if err != nil {
		return err
	}

	icRegistry := interceptor.Registry{}
	err = webrtc.RegisterDefaultInterceptors(&mediaEngine, &icRegistry)
	if err != nil {
		return err
	}
	icRegistry.Add(c.statCollector.GetPionInterceptorFactory())

	api := webrtc.NewAPI(webrtc.WithMediaEngine(&mediaEngine), webrtc.WithInterceptorRegistry(&icRegistry))
	peerConnection, err := api.NewPeerConnection(c.webrtcCfg)
	c.peerConnection = peerConnection
	if err != nil {
		return err
	}

	peerConnection.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
		log.Info().Msgf("Peer Connection State has changed: %s", state.String())
		if state == webrtc.PeerConnectionStateConnected {
			if c.sendOffer {
				c.statCollector.StartCollection(c.testSource.Start())
			}
		} else if state == webrtc.PeerConnectionStateDisconnected {
			if c.sendOffer {
				c.testSource.Stop()
			}
			c.statCollector.StopCollection()
		}
	})

	peerConnection.OnICECandidate(func(candidate *webrtc.ICECandidate) {
		if candidate == nil {
			return
		}

		c.candidatesMux.Lock()
		defer c.candidatesMux.Unlock()

		desc := peerConnection.RemoteDescription()
		if desc == nil {
			c.pendingCandidates = append(c.pendingCandidates, candidate)
		}
		err := c.sendCandidate(candidate)
		if err != nil {
			log.Error().Err(err).Msg("Failed to send candidate")
		}
	})

	peerConnection.OnTrack(func(remoteTrack *webrtc.TrackRemote, receiver *webrtc.RTPReceiver) {
		c.statCollector.StartCollection(uint32(remoteTrack.SSRC()))

		for {
			// read and discard RTP stream
			_, _, readErr := remoteTrack.ReadRTP()
			if readErr != nil {
				log.Error().Err(readErr).Msgf("Error reading from remote track")
				_ = peerConnection.Close()
				break
			}
		}
	})

	if c.sendOffer {

		err = c.testSource.CreateTrack(peerConnection)
		if err != nil {
			log.Error().Err(err).Msg("Failed to create RTP track")
			return err
		}

		offer, err := peerConnection.CreateOffer(nil)
		if err != nil {
			log.Error().Err(err).Msg("Failed to create SDP offer")
			return err
		}

		err = peerConnection.SetLocalDescription(offer)
		if err != nil {
			log.Error().Err(err).Msg("Failed to set local SDP")
			return err
		}

		offerPayload, err := json.Marshal(offer)
		if err != nil {
			log.Error().Err(err).Msg("Failed to marshal offer")
			return err
		}

		err = c.sendSignal(PeerSignalTypeSDP, offerPayload)
		if err != nil {
			log.Error().Err(err).Msg("Failed to send offer")
			return err
		}
	}
	return nil
}

func (c *CaseVideoPion) OnReceiveSignal(signalType PeerSignalType, message []byte) error {
	log.Debug().Msgf("OnReceiveSignal: [%s] %s", signalType, message)
	if signalType == PeerSignalTypeSDP {
		sdp := webrtc.SessionDescription{}
		err := json.Unmarshal(message, &sdp)
		if err != nil {
			log.Error().Err(err).Msg("Failed to unmarshal signalled SDP")
			return err
		}

		err = c.peerConnection.SetRemoteDescription(sdp)
		if err != nil {
			log.Error().Err(err).Msg("Failed to set remote SDP")
			return err
		}

		if sdp.Type == webrtc.SDPTypeAnswer {
			for _, cand := range c.pendingCandidates {
				err := c.sendCandidate(cand)
				if err != nil {
					log.Error().Err(err).Msg("Failed to send candidate")
					return err
				}
			}
			return nil
		}

		answer, err := c.peerConnection.CreateAnswer(nil)
		if err != nil {
			log.Error().Err(err).Msg("Failed to create SDP answer")
			return err
		}

		answerPayload, err := json.Marshal(answer)
		if err != nil {
			log.Error().Err(err).Msg("Failed to marshal SDP answer")
			return err
		}

		err = c.sendSignal(PeerSignalTypeSDP, answerPayload)
		if err != nil {
			log.Error().Err(err).Msg("Failed to send SDP answer")
			return err
		}

		err = c.peerConnection.SetLocalDescription(answer)
		if err != nil {
			log.Error().Err(err).Msg("Failed to set local SDP")
			return err
		}

		for _, cand := range c.pendingCandidates {
			err := c.sendCandidate(cand)
			if err != nil {
				log.Error().Err(err).Msg("Failed to send candidate")
				return err
			}
		}
		return nil
	} else if signalType == PeerSignalTypeCandidates {
		candidate := webrtc.ICECandidateInit{}
		err := json.Unmarshal(message, &candidate)
		if err != nil {
			log.Error().Err(err).Msg("Failed to unmarshal candidate")
			return err
		}

		err = c.peerConnection.AddICECandidate(candidate)
		if err != nil {
			log.Error().Err(err).Msg("Failed to add received ICECandidate")
			return err
		}
		return nil
	}
	return errors.New("unrecognized signalType")
}

func (c *CaseVideoPion) sendCandidate(cand *webrtc.ICECandidate) error {
	payload, err := json.Marshal(cand.ToJSON())
	if err != nil {
		log.Error().Err(err).Msg("Failed to marshal candidate")
	}
	err = c.sendSignal(PeerSignalTypeCandidates, payload)
	if err != nil {
		log.Error().Err(err).Msgf("Error sending candidates signal")
	}

	return nil
}

func (c *CaseVideoPion) Stop() {
	c.statCollector.StopCollection()
	_ = c.peerConnection.Close()
}
