package results

import (
	"github.com/parquet-go/parquet-go"
	"github.com/rs/zerolog/log"
	"os"
)

type ParquetResultsWriter interface {
	WriteRow(row ResultRow)
	Close()
	GetResultFile() (*os.File, error)
}

type parquetResultsWriter struct {
	writeRow       chan ResultRow
	resultFilePath string
}

func NewParquetResultsWriter() (ParquetResultsWriter, error) {
	file, err := os.CreateTemp("", "results-*.parquet")
	if err != nil {
		return nil, err
	}

	log.Info().Msgf("Results will be written to %v", file.Name())

	writer := parquet.NewGenericWriter[ResultRow](file)
	writeRowChan := make(chan ResultRow, 20)

	go func() {
		for row := range writeRowChan {
			_, err := writer.Write([]ResultRow{row})
			if err != nil {
				log.Fatal().Err(err).Msg("Failed to write results to file")
				return
			}
		}
		err = writer.Close()
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to close writer")
			return
		}
		err = file.Close()
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to close result file")
			return
		}
	}()

	return &parquetResultsWriter{
		writeRow:       writeRowChan,
		resultFilePath: file.Name(),
	}, nil
}

func (w *parquetResultsWriter) WriteRow(row ResultRow) {
	w.writeRow <- row
}

func (w *parquetResultsWriter) Close() {
	close(w.writeRow)
}

func (w *parquetResultsWriter) GetResultFile() (*os.File, error) {
	return os.Open(w.resultFilePath)
}
