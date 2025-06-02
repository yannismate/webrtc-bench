const iceServers = ICE_SERVERS.map((iceUrl) => ({urls: iceUrl}));
const doOffer = DO_OFFER;
const statIntervalMs = STAT_INTERVAL_MS;
const maxBitrate = BITRATE;
const fecType = FEC_TYPE;

function log(msg) {
    if (msg instanceof String) {
        sendManagementMessage(JSON.stringify({type: "log", value: msg}))
    } else {
        sendManagementMessage(JSON.stringify({type: "log", value: JSON.stringify(msg)}))
    }
}

window.onerror = function(msg, url, line, col, error) {
    log(`Error: ${error}`);
};

const peerConnection = new RTCPeerConnection({
    iceServers: iceServers
});

let dataChannel;
if (doOffer) {
    dataChannel = peerConnection.createDataChannel("test");
    dataChannel.onopen = () => {
        log("Data channel connected");
    };
}

peerConnection.onconnectionstatechange = e => {
    log("Connection state changed: " + peerConnection.connectionState);
};

peerConnection.onicecandidate = ({candidate}) => {
    if (!candidate) return;

    sendManagementMessage(JSON.stringify({type: "candidates", value: JSON.stringify(candidate)}))
};

peerConnection.ontrack = ({ streams: [ stream ] }) => {
    log("Received stream " + stream.id + ", creating video element for playback.");
    const videoElem = document.createElement('video');
    videoElem.srcObject = stream;
    videoElem.onloadedmetadata = function(e) {
        videoElem.play().then(r => log("Started playing received video."));
    };
};

let statInterval;

async function start() {
    if (doOffer) {
        const stream = await navigator.mediaDevices.getUserMedia({video: true});
        stream.getTracks().forEach(track => peerConnection.addTrack(track, stream));

        log("Sending offer...");
        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);

        // Set max. bitrate
        const sender = peerConnection.getSenders()[0];
        const senderParams = sender.getParameters();
        senderParams.encodings.forEach(e => e.maxBitrate = maxBitrate);
        await sender.setParameters(senderParams);

        sendManagementMessage(JSON.stringify({type: "sdp", value: JSON.stringify(offer)}))
    }

    statInterval = setInterval(() => {
        peerConnection.getStats().then(allStats => {
            const statData = {};
            allStats.forEach(stats => {
                if (stats.type === "inbound-rtp") {
                    statData.timestamp = new Date(Math.round(stats.timestamp)).toISOString();
                    if (!statData.inboundRtp) {
                        statData.inboundRtp = {};
                    }
                    statData.inboundRtp.packetsReceived = stats.packetsReceived;
                    statData.inboundRtp.packetsLost = stats.packetsLost;
                    statData.inboundRtp.jitter = stats.jitter;
                    statData.inboundRtp.millisSinceLastPacket = Math.max(0, Date.now() - Math.floor(stats.lastPacketReceivedTimestamp));
                    statData.inboundRtp.bytesReceived = stats.bytesReceived;
                    statData.inboundRtp.headerBytesReceived = stats.headerBytesReceived;
                    statData.inboundRtp.firCount = stats.firCount;
                    statData.inboundRtp.pliCount = stats.pliCount;
                    statData.inboundRtp.nackCount = stats.nackCount;
                    statData.inboundRtp.framesReceived = stats.framesReceived;
                    statData.inboundRtp.framesDropped = stats.framesDropped;
                    statData.inboundRtp.keyFramesDecoded = stats.keyFramesDecoded;
                    statData.inboundRtp.freezeCount = stats.freezeCount;
                    statData.inboundRtp.totalFreezesDuration = stats.totalFreezesDuration;
                    statData.inboundRtp.retransmittedBytesReceived = stats.retransmittedBytesReceived;
                    statData.inboundRtp.retransmittedPacketsReceived = stats.retransmittedPacketsReceived;
                } else if (stats.type === "outbound-rtp") {
                    statData.timestamp = new Date(Math.round(stats.timestamp)).toISOString();
                    statData.outboundRtp = {
                        packetsSent: stats.packetsSent,
                        bytesSent: stats.bytesSent,
                        headerBytesSent: stats.headerBytesSent,
                        nackCount: stats.nackCount,
                        firCount: stats.firCount,
                        pliCount: stats.pliCount,
                        framesSent: stats.framesSent,
                        targetBitrate: stats.targetBitrate
                    };
                } else if (stats.type === "remote-inbound-rtp") {
                    if (!statData.outboundRtp) {
                        statData.outboundRtp = {};
                    }
                    statData.outboundRtp.roundTripTime = stats.roundTripTime;
                } else if (stats.type === "remote-outbound-rtp") {
                    if (!statData.inboundRtp) {
                        statData.inboundRtp = {};
                    }
                    statData.inboundRtp.roundTripTime = stats.roundTripTime;
                }
            });
            sendManagementMessage(JSON.stringify({type: "stats", value: JSON.stringify(statData)}))
        });
    }, statIntervalMs);
}

async function stop() {
    clearInterval(statInterval);
    peerConnection.close();
}

async function receiveManagementMessage(type, msgString) {
    if (type === "sdp") {
        let sdpObj = JSON.parse(msgString);
        if (fecType !== "ulp") {
            sdpObj.sdp = sdpObj.sdp.split("\n").filter(line => !line.includes("ulpfec")).join("\n");
        }
        log("SDP: " + sdpObj.sdp);

        await peerConnection.setRemoteDescription(new RTCSessionDescription(sdpObj));

        if (!doOffer) {
            log("Sending answer");
            const answer = await peerConnection.createAnswer();
            await peerConnection.setLocalDescription(answer);

            sendManagementMessage(JSON.stringify({type: "sdp", value: JSON.stringify(answer)}));
        } else {
            log("Set remote description, RTC should be ready.");
        }
    } else if (type === "candidates") {
        await peerConnection.addIceCandidate(new RTCIceCandidate(JSON.parse(msgString)));
    }
}

// Required to return for chromedp evaluation
[""]