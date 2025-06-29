package cases

import (
	"encoding/json"
	"errors"
	"github.com/pion/webrtc/v4"
	"github.com/rs/zerolog/log"
	"sync"
	"webrtc-bench/internal/cases/stats"
)

type CaseConnectPion struct {
	sendSignal     func(signalType PeerSignalType, data []byte) error
	webrtcCfg      webrtc.Configuration
	sendOffer      bool
	peerConnection *webrtc.PeerConnection

	pendingCandidates []*webrtc.ICECandidate
	candidatesMux     sync.Mutex
	statCollector     stats.StatCollector
}

func (c *CaseConnectPion) Configure(config PeerCaseConfig, sendSignal func(signalType PeerSignalType, data []byte) error, statCollector stats.StatCollector) error {
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
	return nil
}

func (c *CaseConnectPion) Start() error {
	peerConnection, err := webrtc.NewPeerConnection(c.webrtcCfg)
	c.peerConnection = peerConnection
	if err != nil {
		return err
	}

	peerConnection.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
		log.Info().Msgf("Peer Connection State has changed: %s", state.String())
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
		err = c.sendCandidate(candidate)
		if err != nil {
			log.Error().Err(err).Msg("Failed to send new candidate")
		}
	})

	if c.sendOffer {
		dataChannel, err := peerConnection.CreateDataChannel("test", nil)
		if err != nil {
			log.Error().Err(err).Msgf("Error creating data channel")
			return err
		}

		dataChannel.OnOpen(func() {
			log.Info().Msgf("Data channel opened!")
		})

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

func (c *CaseConnectPion) OnReceiveSignal(signalType PeerSignalType, message []byte) error {
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
				err = c.sendCandidate(cand)
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
			err = c.sendCandidate(cand)
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

func (c *CaseConnectPion) GetExtraResultFiles() *map[string][]byte {
	return nil
}

func (c *CaseConnectPion) sendCandidate(cand *webrtc.ICECandidate) error {
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

func (c *CaseConnectPion) Stop() {
	_ = c.peerConnection.Close()
}
