//
// Created by yannis on 8/5/25.
//

#include "ffmpeg_receiver_sink.h"

#include <iostream>
#include <ostream>
#include <rtc_base/thread.h>

void FFMpegReceiverSink::Start() {
    auto ffmpeg_command = "ffmpeg -hide_banner -loglevel error "
                          "-f rawvideo -pix_fmt yuv420p -s 1280x720 -use_wallclock_as_timestamps 1 -i pipe: "
                          "-vf drawtext=\"fontsize=30:text='%{gmtime\\:%T.%N} - %{frame_num}':fontcolor=white:x=4:y=38:box=1:boxcolor=black@0.8\" "
                          "-vsync vfr -c:v libx264 -preset ultrafast -crf 18 -tune zerolatency -f mpegts received_video.ts";
    std::cout << "[ffmpeg-recv] Running ffmpeg for sink: " << ffmpeg_command << std::endl;
    ffmpegProcess = popen(ffmpeg_command, "w");
}

void FFMpegReceiverSink::Stop() {
    if (ffmpegProcess != nullptr) {
        pclose(ffmpegProcess);
        ffmpegProcess = nullptr;
    }
}


void FFMpegReceiverSink::OnFrame(const webrtc::VideoFrame &frame) {
    if (ffmpegProcess == nullptr) {
        std::cout << "[ffmpeg-recv] Cannot save received frame, ffmpeg is not running yet." << std::endl;
        return;
    }

    auto buffer = frame.video_frame_buffer()->GetI420();

    if (buffer == nullptr) {
        std::cout << "[ffmpeg-recv] Received frame buffer is null." << std::endl;
        return;
    }

    int width = buffer->width();
    int height = buffer->height();

    for (int y = 0; y < height; ++y) {
        fwrite(buffer->DataY() + y * buffer->StrideY(), 1, static_cast<size_t>(width), ffmpegProcess);
    }
    for (int y = 0; y < height / 2; ++y) {
        fwrite(buffer->DataU() + y * buffer->StrideU(), 1, static_cast<size_t>(width / 2), ffmpegProcess);
    }
    for (int y = 0; y < height / 2; ++y) {
        fwrite(buffer->DataV() + y * buffer->StrideV(), 1, static_cast<size_t>(width / 2), ffmpegProcess);
    }

    fflush(ffmpegProcess);
}
