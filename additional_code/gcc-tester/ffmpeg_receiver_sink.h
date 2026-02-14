//
// Created by yannis on 8/5/25.
//

#ifndef GCC_TESTER_FFMPEG_RECEIVER_SINK_H
#define GCC_TESTER_FFMPEG_RECEIVER_SINK_H
#include <api/video/video_frame.h>
#include <api/video/video_sink_interface.h>

class FFMpegReceiverSink : public webrtc::VideoSinkInterface<webrtc::VideoFrame> {
public:
    void Start();
    void Stop();
    void OnFrame(const webrtc::VideoFrame& frame) override;
private:
    FILE* ffmpegProcess = nullptr;
};

#endif // GCC_TESTER_FFMPEG_RECEIVER_SINK_H
