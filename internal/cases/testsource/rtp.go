package testsource

import (
	"github.com/mengelbart/syncodec"
	"github.com/pion/webrtc/v4"
	"github.com/pion/webrtc/v4/pkg/media"
	"github.com/rs/zerolog/log"
	"io"
	"time"
	"webrtc-bench/internal/cases/stats"
)

type FakeRTPDataWriter interface {
	CreateTrack(peerConnection *webrtc.PeerConnection) error
	Start() (uint32, uint32)
	SetBitrate(targetBitrate int)
	Stop()
}

type fakeRTPDataWriter struct {
	InitialTargetBitrate int

	statsCollector stats.StatCollector
	track          *webrtc.TrackLocalStaticSample
	codec          syncodec.Codec
	rtpSender      *webrtc.RTPSender
}

func NewFakeRTPDataWriter(targetBitrate int) FakeRTPDataWriter {
	return &fakeRTPDataWriter{
		InitialTargetBitrate: targetBitrate,
	}
}

func (fw *fakeRTPDataWriter) CreateTrack(peerConnection *webrtc.PeerConnection) error {
	localSample, err := webrtc.NewTrackLocalStaticSample(webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeH264}, "video", "pion")
	if err != nil {
		return err
	}

	fw.track = localSample

	rtpSender, err := peerConnection.AddTrack(localSample)
	if err != nil {
		return err
	}
	fw.rtpSender = rtpSender

	codec, err := syncodec.NewStatisticalEncoder(fw, syncodec.WithInitialTargetBitrate(fw.InitialTargetBitrate))
	if err != nil {
		return err
	}
	fw.codec = codec

	return nil
}

func (fw *fakeRTPDataWriter) Start() (uint32, uint32) {
	go fw.codec.Start()

	go func() {
		for {
			if _, _, err := fw.rtpSender.ReadRTCP(); err != nil {
				if err == io.EOF {
					log.Debug().Err(err).Msg("Fake rtpSender stopped")
					return
				}
				log.Error().Err(err).Msg("Fake rtpSender returned error!")
				return
			}
		}

	}()

	return uint32(fw.rtpSender.GetParameters().Encodings[0].SSRC), uint32(fw.rtpSender.GetParameters().Encodings[0].RTX.SSRC)
}

func (fw *fakeRTPDataWriter) SetBitrate(targetBitrate int) {
	// Target bitrate should always be at least 30kbps, as this is the minimum bitrate WebRTC video
	fw.codec.SetTargetBitrate(max(targetBitrate, 30_000))
}

func (fw *fakeRTPDataWriter) Stop() {
	_ = fw.codec.Close()
}

func (fw *fakeRTPDataWriter) WriteFrame(frame syncodec.Frame) {
	err := fw.track.WriteSample(media.Sample{
		Data:      frame.Content,
		Timestamp: time.Time{},
		Duration:  frame.Duration,
	})
	if err != nil {
		log.Error().Err(err).Msg("Fake track write sample error")
	}
}
