/**
 * test_ws_proxy.ts — End-to-End Automated Verification Test for WebSocket Proxy
 *
 * Tests:
 * 1. Server initialization and upgrade routing
 * 2. Subscription to /ws/feed/gate, /ws/feed/area, /ws/events/gate, /ws/events/area, /ws/alerts
 * 3. Channel isolation (Gate frames only go to Gate subscribers, not Area subscribers)
 * 4. Inbound publisher forwarding (Python publisher -> Node WS proxy -> Browser subscribers)
 * 5. Direct channelManager broadcasting
 * 6. Disconnect cleanup
 */
import http from 'http';
import WebSocket from 'ws';
import express from 'express';
import { setupWebSocketProxy, channelManager, pythonConnector } from '../ws';

const TEST_PORT = 3099;

function waitForMessage(ws: WebSocket, predicate: (data: any) => boolean, timeoutMs = 4000): Promise<any> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      ws.off('message', onMessage);
      reject(new Error(`Timed out after ${timeoutMs}ms waiting for matching message`));
    }, timeoutMs);

    function onMessage(data: WebSocket.RawData) {
      try {
        const parsed = JSON.parse(data.toString('utf8'));
        if (predicate(parsed)) {
          clearTimeout(timer);
          ws.off('message', onMessage);
          resolve(parsed);
        }
      } catch {
        // ignore non-json
      }
    }

    ws.on('message', onMessage);
  });
}

function connectWs(path: string): Promise<WebSocket> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`ws://localhost:${TEST_PORT}${path}`);
    const timer = setTimeout(() => {
      reject(new Error(`Timed out connecting to ws://localhost:${TEST_PORT}${path}`));
    }, 4000);

    ws.on('open', () => {
      clearTimeout(timer);
      resolve(ws);
    });

    ws.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

async function runTests() {
  console.log('======================================================================');
  console.log('SentriAI - FDN-WS-PROXY Verification Test Suite');
  console.log('======================================================================');

  const app = express();
  const server = http.createServer(app);
  setupWebSocketProxy(server);

  await new Promise<void>((resolve) => {
    server.listen(TEST_PORT, () => {
      console.log(`[1/6] Test HTTP/WS Server listening on port ${TEST_PORT}`);
      resolve();
    });
  });

  const socketsToClose: WebSocket[] = [];

  try {
    // 2. Connect subscribers to all 5 standard channels
    console.log('\n[2/6] Connecting 5 client subscribers to respective channels...');
    const subGateFeed = await connectWs('/ws/feed/gate');
    socketsToClose.push(subGateFeed);
    const subAreaFeed = await connectWs('/ws/feed/area');
    socketsToClose.push(subAreaFeed);
    const subGateEvents = await connectWs('/ws/events/gate');
    socketsToClose.push(subGateEvents);
    const subAreaEvents = await connectWs('/ws/events/area');
    socketsToClose.push(subAreaEvents);
    const subAlerts = await connectWs('/ws/alerts');
    socketsToClose.push(subAlerts);

    console.log('  [OK] 5 subscriber sockets connected successfully');
    const stats = channelManager.getStats();
    console.log('  [OK] ChannelManager stats:', JSON.stringify(stats));
    if (stats['feed:GATE-01'] < 1 || stats['feed:BAI-KIEM'] < 1) {
      throw new Error('Subscriber channel counts do not match expected subscriptions');
    }

    // 3. Test Inbound Publisher -> Gate Feed forwarding & Channel Isolation
    console.log('\n[3/6] Testing Python Inbound Publisher -> Feed Forwarding & Channel Isolation...');
    const publisherGateFeed = await connectWs('/ws/publish/feed/GATE-01');
    socketsToClose.push(publisherGateFeed);

    const testFrame = {
      type: 'frame',
      cameraId: 'GATE-01',
      timestamp: Date.now(),
      image: 'data:image/jpeg;base64,TEST_FRAME_DATA_12345',
      fps: 15.0,
      detections: [
        {
          bbox: [100, 150, 300, 400],
          class: 'truck',
          confidence: 0.96,
          label: 'Xe tai',
          status: 'KNOWN',
        },
      ],
    };

    // Prepare listener on subGateFeed
    const framePromise = waitForMessage(subGateFeed, (msg) => msg.type === 'frame' && msg.cameraId === 'GATE-01');

    // Also verify subAreaFeed does NOT receive this Gate frame
    let areaReceivedGateFrame = false;
    const areaFrameListener = (data: WebSocket.RawData) => {
      try {
        const msg = JSON.parse(data.toString('utf8'));
        if (msg.type === 'frame' && msg.cameraId === 'GATE-01') {
          areaReceivedGateFrame = true;
        }
      } catch {}
    };
    subAreaFeed.on('message', areaFrameListener);

    // Send frame from publisher
    publisherGateFeed.send(JSON.stringify(testFrame));

    const receivedFrame = await framePromise;
    console.log('  [OK] subGateFeed received frame with cameraId:', receivedFrame.cameraId);
    if (receivedFrame.detections[0].class !== 'truck') {
      throw new Error('Received frame detection content mismatch');
    }

    // Wait a brief tick to verify subAreaFeed didn't get it
    await new Promise((r) => setTimeout(r, 100));
    subAreaFeed.off('message', areaFrameListener);
    if (areaReceivedGateFrame) {
      throw new Error('Channel isolation violation: Area feed received Gate frame!');
    }
    console.log('  [OK] Channel isolation verified: Area feed did not receive Gate feed frame');

    // 4. Test Inbound Publisher -> Gate Events forwarding
    console.log('\n[4/6] Testing Gate Event Inbound Publishing...');
    const publisherGateEvents = await connectWs('/ws/publish/events/gate');
    socketsToClose.push(publisherGateEvents);

    const testGateEvent = {
      type: 'gate_event',
      id: 'event-uuid-999',
      cameraId: 'GATE-01',
      lane: 'IN_1',
      licensePlate: '51A-99999',
      status: 'KNOWN',
      confidence: 0.98,
      timestamp: new Date().toISOString(),
    };

    const eventPromise = waitForMessage(subGateEvents, (msg) => msg.type === 'gate_event' && msg.licensePlate === '51A-99999');
    publisherGateEvents.send(JSON.stringify(testGateEvent));

    const receivedEvent = await eventPromise;
    console.log('  [OK] subGateEvents received gate_event:', receivedEvent.licensePlate, receivedEvent.status);

    // 5. Test Direct Broadcasting from Node.js (channelManager methods)
    console.log('\n[5/6] Testing Direct Node.js channelManager broadcasting...');
    const areaEventPromise = waitForMessage(subAreaEvents, (msg) => msg.type === 'zone_violation' && msg.objectLabel === 'Xe may');
    channelManager.broadcastAreaEvent({
      id: 'viol-uuid-111',
      cameraId: 'BAI-KIEM',
      zoneId: 'zone-uuid-222',
      zoneName: 'Khu vuc cam',
      objectLabel: 'Xe may',
      status: 'OPEN',
      enteredAt: new Date().toISOString(),
    });
    const receivedAreaEvent = await areaEventPromise;
    console.log('  [OK] subAreaEvents received zone_violation:', receivedAreaEvent.objectLabel, receivedAreaEvent.status);

    const alertPromise = waitForMessage(subAlerts, (msg) => msg.type === 'alert' && msg.title === 'Canh bao test');
    channelManager.broadcastAlert({
      level: 'critical',
      title: 'Canh bao test',
      message: 'Test message broadcast to /ws/alerts',
      cameraId: 'BAI-KIEM',
      timestamp: new Date().toISOString(),
    });
    const receivedAlert = await alertPromise;
    console.log('  [OK] subAlerts received urgent alert:', receivedAlert.title);

    // 6. Test Disconnection & Cleanup
    console.log('\n[6/6] Testing Client Disconnection & Cleanup...');
    for (const ws of socketsToClose) {
      ws.close();
    }
    // Wait for close events to process
    await new Promise((r) => setTimeout(r, 200));
    const statsAfter = channelManager.getStats();
    console.log('  [OK] ChannelManager stats after disconnect:', JSON.stringify(statsAfter));
    const totalRemaining = Object.values(statsAfter).reduce((a, b) => a + b, 0);
    if (totalRemaining !== 0) {
      throw new Error(`Expected 0 remaining subscribers, got ${totalRemaining}`);
    }
    console.log('  [OK] All sockets cleanly unsubscribed and memory cleared');

  } finally {
    // Teardown
    pythonConnector.stop();
    for (const ws of socketsToClose) {
      if (ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    }
    await new Promise<void>((resolve) => {
      server.close(() => {
        console.log('  [OK] Test server closed cleanly');
        resolve();
      });
    });
  }

  console.log('\n======================================================================');
  console.log('ALL WEBSOCKET PROXY TESTS PASSED SUCCESSFULLY! (100% PASS)');
  console.log('======================================================================');
  process.exit(0);
}

runTests().catch((err) => {
  console.error('Test failed with error:', err);
  process.exit(1);
});
