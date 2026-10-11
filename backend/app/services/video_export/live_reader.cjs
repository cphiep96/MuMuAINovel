// Headless WebRTC text reader using Lingua Desk's tested OpenCodex sideband bridge.
const fs = require('node:fs');
const path = require('node:path');

function sameReading(actual, expected) {
  const normalize = text => text.normalize('NFKC').toLowerCase().replace(/\p{P}/gu, '').replace(/[\p{Z}\s]+/gu, ' ').trim();
  return Boolean(actual.trim()) && normalize(actual) === normalize(expected);
}
async function read(input) {
  if (typeof input.text !== 'string' || !input.text.trim() || input.text.length > 2000) throw Error('Text must contain 1–2000 characters');
  const { createLiveDub, voices } = require(input.bridgePath);
  if (!voices.includes(input.voice)) throw Error('Unsupported gpt-live voice');
  const { chromium } = require(input.playwrightPath);
  const live = createLiveDub({textRead: true, baseUrl: input.baseUrl});
  let browser;
  try {
    browser = await chromium.launch({executablePath: input.browserPath, headless: true,
      args: ['--force-webrtc-ip-handling-policy=default_public_interface_only','--autoplay-policy=no-user-gesture-required']});
    const page = await browser.newPage();
    await page.route('http://127.0.0.1:4189/**', route => route.fulfill({contentType:'text/html',body:'<!doctype html><title>Local narration worker</title>'}));
    await page.goto('http://127.0.0.1:4189/');
    await page.exposeFunction('liveBridge',(action,payload) => live.request(action,payload));
    const result = await page.evaluate(async ({text,voice,timeout}) => {
      const id=crypto.randomUUID(), pc=new RTCPeerConnection(), context=new AudioContext();
      const destination=context.createMediaStreamDestination(), gain=context.createGain(), oscillator=context.createOscillator();
      gain.gain.value=0;oscillator.connect(gain);gain.connect(destination);oscillator.start();
      const deadline=Date.now()+timeout;
      let recorder,chunks=[], ready=false, sent=false, done;
      pc.ontrack=event=>{const stream=new MediaStream([event.track]);recorder=new MediaRecorder(stream);recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};recorder.start(100);};
      const check=()=>{if(Date.now()>deadline)throw Error('gpt-live narration timed out');if(['failed','disconnected','closed'].includes(pc.connectionState))throw Error('WebRTC disconnected');};
      try {
        await context.resume();pc.addTransceiver(destination.stream.getAudioTracks()[0],{direction:'sendrecv'});
        await pc.setLocalDescription(await pc.createOffer());
        while(pc.iceGatheringState!=='complete'){check();await new Promise(r=>setTimeout(r,50));}
        const response=await window.liveBridge('create',{id,sdp:pc.localDescription.sdp,voice});
        await pc.setRemoteDescription({type:'answer',sdp:response.answer});
        while(!done){
          check();const response=await window.liveBridge('events',{id});
          for(const event of response.events||[]){
            if(event.type==='error'||event.type==='closed')throw Error(event.message||'Live control ended');
            if(event.type==='ready')ready=true;
            if(event.type==='done')done=event;
          }
          if(ready&&!sent&&pc.connectionState==='connected'&&recorder){await window.liveBridge('read',{id,text,language:'vi-VN'});sent=true;}
          if(!done)await new Promise(r=>setTimeout(r,120));
        }
        if(!sent)throw Error('Received audio before text was requested');
        if(done.audio)return {transcript:done.transcript,audio:done.audio,format:'wav'};
        await new Promise(r=>setTimeout(r,400));
        if(!recorder||recorder.state!=='recording')throw Error('No audio received');
        await new Promise(resolve=>{recorder.onstop=resolve;recorder.stop();});
        const blob=new Blob(chunks,{type:recorder.mimeType}),bytes=new Uint8Array(await blob.arrayBuffer());
        if(!bytes.length)throw Error('Empty recording');
        let binary='';for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
        return {transcript:done.transcript,audio:btoa(binary),format:'webm'};
      } finally {
        if(recorder?.state==='recording')recorder.stop();pc.close();destination.stream.getTracks().forEach(t=>t.stop());oscillator.stop();await context.close();await window.liveBridge('stop',{id}).catch(()=>{});
      }
    },{text:input.text,voice:input.voice,timeout:input.timeoutMs||60000});
    if(!sameReading(result.transcript||'',input.text))throw Error('gpt-live did not read the requested text verbatim');
    const bytes=Buffer.from(result.audio,'base64');
    if(!bytes.length||bytes.length>6*1024*1024)throw Error('Invalid narration size');
    if(result.format==='wav'){
      if(bytes.toString('ascii',0,4)!=='RIFF'||bytes.toString('ascii',8,12)!=='WAVE'||bytes.length<46)throw Error('Invalid WAV');
      let voiced=false;for(let i=44;i+1<bytes.length;i+=2)if(Math.abs(bytes.readInt16LE(i))>32){voiced=true;break;}
      if(!voiced)throw Error('Live narration was silent');
    }
    fs.mkdirSync(path.dirname(input.output),{recursive:true});fs.writeFileSync(input.output,bytes);
    return {ok:true,format:result.format,bytes:bytes.length,transcript:result.transcript};
  } finally {live.close();if(browser)await browser.close();}
}
module.exports={sameReading,read};
if(require.main===module){
  let data='';process.stdin.setEncoding('utf8');process.stdin.on('data',chunk=>{data+=chunk;if(data.length>20000){process.stderr.write('Request too large');process.exit(1);}});
  process.stdin.on('end',()=>{
    read(JSON.parse(data)).then(result=>process.stdout.write(JSON.stringify(result)+'\n')).catch(error=>{process.stderr.write(String(error.message)+'\n');process.exitCode=1;});
  });
}
