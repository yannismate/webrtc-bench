package seqrecorder

import (
	"fmt"
	"github.com/pion/interceptor"
	"github.com/pion/rtp"
	"github.com/rs/zerolog/log"
	"os"
	"strconv"
	"time"
)

type seqRecorder struct {
	tempFiles map[uint32]*os.File
}

type Factory struct {
	createdSeqRecorders []*seqRecorder
}

func (s *Factory) GetFiles() []*os.File {
	var files []*os.File
	for _, sr := range s.createdSeqRecorders {
		for _, f := range sr.tempFiles {
			files = append(files, f)
		}
	}
	return files
}

func (s *Factory) NewInterceptor(_ string) (interceptor.Interceptor, error) {
	newRecorder := seqRecorder{tempFiles: make(map[uint32]*os.File)}
	s.createdSeqRecorders = append(s.createdSeqRecorders, &newRecorder)
	return &newRecorder, nil
}

func (s *seqRecorder) BindRTCPReader(reader interceptor.RTCPReader) interceptor.RTCPReader {
	return reader
}

func (s *seqRecorder) BindRTCPWriter(writer interceptor.RTCPWriter) interceptor.RTCPWriter {
	return writer
}

func (s *seqRecorder) BindLocalStream(info *interceptor.StreamInfo, writer interceptor.RTPWriter) interceptor.RTPWriter {
	if info.SSRCRetransmission == 0 {
		log.Info().Msgf("Not recording timings for SSRC %d - likely RTX.", info.SSRC)
		return writer
	}
	ssrc := info.SSRC
	tempFile, err := os.CreateTemp("", "timing-out-"+strconv.Itoa(int(ssrc))+"-*.csv")
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to create temp file for timing logs")
	}
	log.Info().Msgf("Saving timings for SSRC %d to %s", ssrc, tempFile.Name())

	s.tempFiles[ssrc] = tempFile
	_, err = tempFile.WriteString(fmt.Sprintf("Timestamp,HeaderTimestamp,SeqNum\n"))
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to write timing log header")
	}

	return interceptor.RTPWriterFunc(
		func(header *rtp.Header, payload []byte, attributes interceptor.Attributes) (int, error) {
			_, err = tempFile.WriteString(fmt.Sprintf("%d,%d,%d\n", time.Now().UnixMicro(), header.Timestamp, header.SequenceNumber))
			if err != nil {
				log.Error().Err(err).Msg("Failed to write timing log header")
			}
			return writer.Write(header, payload, attributes)
		},
	)
}

func (s *seqRecorder) UnbindLocalStream(info *interceptor.StreamInfo) {
	if file, ok := s.tempFiles[info.SSRC]; ok {
		_ = file.Close()
	}
}

func (s *seqRecorder) BindRemoteStream(info *interceptor.StreamInfo, reader interceptor.RTPReader) interceptor.RTPReader {
	if info.SSRCRetransmission == 0 {
		log.Info().Msgf("Not recording timings for SSRC %d - likely RTX.", info.SSRC)
		return reader
	}
	ssrc := info.SSRC
	tempFile, err := os.CreateTemp("", "timing-in-"+strconv.Itoa(int(ssrc))+"-*.csv")
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to create temp file for timing logs")
	}
	s.tempFiles[ssrc] = tempFile
	_, err = tempFile.WriteString(fmt.Sprintf("Timestamp,HeaderTimestamp,SeqNum\n"))
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to write timing log header")
	}
	log.Info().Msgf("Saving timings for SSRC %d to %s", ssrc, tempFile.Name())

	return interceptor.RTPReaderFunc(
		func(buf []byte, attr interceptor.Attributes) (int, interceptor.Attributes, error) {
			n, attr, err := reader.Read(buf, attr)
			if err != nil {
				return 0, nil, err
			}
			header, err := attr.GetRTPHeader(buf)
			if err != nil {
				log.Error().Err(err).Msg("Failed to get RTP Header")
				return reader.Read(buf, attr)
			}

			_, err = tempFile.WriteString(fmt.Sprintf("%d,%d,%d\n", time.Now().UnixMicro(), header.Timestamp, header.SequenceNumber))
			if err != nil {
				log.Error().Err(err).Msg("Failed to write timing log header")
			}
			return n, attr, err
		},
	)
}

func (s *seqRecorder) UnbindRemoteStream(info *interceptor.StreamInfo) {
	if file, ok := s.tempFiles[info.SSRC]; ok {
		_ = file.Close()
	}
}

func (s *seqRecorder) Close() error {
	for _, file := range s.tempFiles {
		_ = file.Close()
	}
	return nil
}
