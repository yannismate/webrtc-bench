const statIntervalMs = STAT_INTERVAL_MS;

function log(msg) {
    if (msg instanceof String) {
        sendManagementMessage(JSON.stringify({type: "log", value: msg}))
    } else {
        sendManagementMessage(JSON.stringify({type: "log", value: JSON.stringify(msg)}))
    }
}

function getPeerConnection() {
    const rtcPeerConnections = window.peerConnections;
    if (rtcPeerConnections.length === 0) {
        log("Error getting peer connection, no peer connection found!");
        throw new Error("Error getting peer connection, no peer connection found!");
    }
    return rtcPeerConnections[rtcPeerConnections.length - 1];
}

let peerConnection;
setInterval(async () => {
    if (!peerConnection) {
        peerConnection = getPeerConnection();
    }
    const allStats = await peerConnection.getStats()
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
}, statIntervalMs);

// Required to return for chromedp evaluation
[""]