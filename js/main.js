import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js';
import {GLTFLoader} from 'https://cdn.jsdelivr.net/npm/three@0.180.0/examples/jsm/loaders/GLTFLoader.js';
const $=s=>document.querySelector(s), load=$('#loading'), prog=$('#progress'), err=$('#error');
const scene=new THREE.Scene(); scene.background=new THREE.Color(0x91a8b7); scene.fog=new THREE.Fog(0x91a8b7,180,900);
const camera=new THREE.PerspectiveCamera(62,innerWidth/innerHeight,.08,1600); const renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'}); renderer.setPixelRatio(Math.min(devicePixelRatio,1.35)); renderer.setSize(innerWidth,innerHeight); renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap; document.body.prepend(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xddeeff,0x59634b,2.0)); const sun=new THREE.DirectionalLight(0xffffff,2.2);sun.position.set(80,130,40);sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);scene.add(sun);
let hero=null,mixer=null,clips={},state='IDLE',groundMeshes=[],vy=0,grounded=false,yaw=0,pitch=.32,camDist=5.3,joy={x:0,y:0,power:0},keys={}; const ray=new THREE.Raycaster(); const clock=new THREE.Clock();
function fail(s){err.style.display='block';err.textContent=s;load.style.display='none'}
const manager=new THREE.LoadingManager();manager.onProgress=(u,a,b)=>prog.textContent=`Loading ${Math.round(a/b*100)}%`;manager.onError=u=>console.warn('asset',u);
const gltf=new GLTFLoader(manager);

function loadGLB(url){return new Promise((r,j)=>gltf.load(url,r,undefined,j))}
async function loadPackedGLB(url,label='asset'){
  // Generated assets larger than 20 MB are stored as url.part000... + url.parts.json.
  // This keeps every GitHub-uploaded file below 25 MB while still loading one GLB in memory.
  try{
    const manifestResponse=await fetch(url+'.parts.json',{cache:'no-store'});
    if(manifestResponse.ok){
      const manifest=await manifestResponse.json();
      if(!Array.isArray(manifest.parts)||!manifest.parts.length)throw new Error('manifest part kosong');
      const base=url.slice(0,url.lastIndexOf('/')+1);
      const buffers=[];let total=0;
      for(let i=0;i<manifest.parts.length;i++){
        prog.textContent=`Loading ${label} ${i+1}/${manifest.parts.length}`;
        const response=await fetch(base+manifest.parts[i]);
        if(!response.ok)throw new Error(`${manifest.parts[i]} HTTP ${response.status}`);
        const buffer=await response.arrayBuffer();buffers.push(buffer);total+=buffer.byteLength;
      }
      if(manifest.totalBytes&&total!==manifest.totalBytes)console.warn('Ukuran hasil chunk berbeda',total,manifest.totalBytes);
      const merged=new Uint8Array(total);let offset=0;
      for(const buffer of buffers){merged.set(new Uint8Array(buffer),offset);offset+=buffer.byteLength}
      return await new Promise((resolve,reject)=>gltf.parse(merged.buffer,base,resolve,reject));
    }
  }catch(e){console.warn('Split loader fallback:',e)}
  return loadGLB(url);
}

Promise.all([
  loadPackedGLB('assets/map/map.glb','map'),
  loadPackedGLB('assets/character/character_rigged.glb','character')
]).then(([map,ch])=>{scene.add(map.scene);map.scene.traverse(o=>{if(o.isMesh){o.receiveShadow=true;groundMeshes.push(o)}});hero=ch.scene;scene.add(hero);hero.traverse(o=>{if(o.isMesh){o.castShadow=true;o.frustumCulled=true}});mixer=new THREE.AnimationMixer(hero);for(const c of ch.animations)clips[c.name.toUpperCase()]=mixer.clipAction(c); setAnim('IDLE');spawn();load.style.display='none'}).catch(e=>fail('Aset GLB belum tersedia. Jalankan tools/prepare_assets.py memakai Blender terlebih dahulu. '+e.message));
function setAnim(n){if(state===n&&clips[n])return;const next=clips[n]||clips.IDLE;if(!next)return;Object.values(clips).forEach(a=>{if(a!==next)a.fadeOut(.18)});next.reset().fadeIn(.18).play();state=n}
function groundAt(p){ray.set(new THREE.Vector3(p.x,p.y+6,p.z),new THREE.Vector3(0,-1,0));const h=ray.intersectObjects(groundMeshes,true);return h.length?h[0].point.y:null}
function spawn(){const box=new THREE.Box3().setFromObject(scene);hero.position.set((box.min.x+box.max.x)/2,box.max.y+10,(box.min.z+box.max.z)/2);let y=groundAt(hero.position);if(y==null){hero.position.set(0,30,0);y=groundAt(hero.position)}if(y!=null)hero.position.y=y;}
function update(dt){if(!hero)return;let ix=joy.x,iy=joy.y; if(keys.KeyW)iy=1;if(keys.KeyS)iy=-1;if(keys.KeyA)ix=-1;if(keys.KeyD)ix=1;let power=Math.min(1,Math.hypot(ix,iy));if(keys.ShiftLeft&&power)power=1; const f=new THREE.Vector3(-Math.sin(yaw),0,-Math.cos(yaw)),r=new THREE.Vector3(Math.cos(yaw),0,-Math.sin(yaw));const dir=f.multiplyScalar(iy).add(r.multiplyScalar(ix));if(dir.lengthSq())dir.normalize();const speed=power>.65?6.1:power>.12?2.8:0;if(speed){hero.position.addScaledVector(dir,speed*dt);const target=Math.atan2(dir.x,dir.z);let d=Math.atan2(Math.sin(target-hero.rotation.y),Math.cos(target-hero.rotation.y));hero.rotation.y+=d*Math.min(1,dt*10)}
vy-=18*dt;hero.position.y+=vy*dt;const gy=groundAt(hero.position);grounded=gy!=null&&hero.position.y<=gy+.18&&vy<=0;if(grounded){hero.position.y=gy;vy=0} if(!grounded)setAnim(vy>.3?'JUMP_START':'JUMP_AIR');else if(state==='JUMP_AIR'||state==='JUMP_START')setAnim('JUMP_LAND');else setAnim(speed?(power>.65?'RUN':'WALK'):'IDLE');mixer?.update(dt);
const target=hero.position.clone().add(new THREE.Vector3(0,1.55,0));const cp=new THREE.Vector3(Math.sin(yaw)*Math.cos(pitch)*camDist,Math.sin(pitch)*camDist+1.0,Math.cos(yaw)*Math.cos(pitch)*camDist).add(target);camera.position.lerp(cp,1-Math.exp(-10*dt));camera.lookAt(target)}
function jump(){if(hero&&grounded){vy=7.2;grounded=false;setAnim('JUMP_START')}}
function loop(){requestAnimationFrame(loop);const dt=Math.min(.033,clock.getDelta());update(dt);renderer.render(scene,camera)}loop();
addEventListener('resize',()=>{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight)});addEventListener('keydown',e=>{keys[e.code]=1;if(e.code==='Space')jump()});addEventListener('keyup',e=>keys[e.code]=0);
const jb=$('#joy'),kn=jb.querySelector('i');let jid=null;function jmove(e){const b=jb.getBoundingClientRect(),x=e.clientX-(b.left+b.width/2),y=e.clientY-(b.top+b.height/2),m=Math.min(48,Math.hypot(x,y)),a=Math.atan2(y,x);const dx=Math.cos(a)*m,dy=Math.sin(a)*m;kn.style.transform=`translate(${dx}px,${dy}px)`;joy={x:dx/48,y:-dy/48,power:m/48}}jb.onpointerdown=e=>{jid=e.pointerId;jb.setPointerCapture(jid);jmove(e)};jb.onpointermove=e=>{if(e.pointerId===jid)jmove(e)};jb.onpointerup=jb.onpointercancel=e=>{if(e.pointerId===jid){jid=null;joy={x:0,y:0,power:0};kn.style.transform='translate(0,0)'}};
$('#jump').onpointerdown=e=>{e.stopPropagation();jump()};let cid=null,last=null;renderer.domElement.onpointerdown=e=>{if(e.clientX<innerWidth*.32)return;cid=e.pointerId;last=[e.clientX,e.clientY];renderer.domElement.setPointerCapture(cid)};renderer.domElement.onpointermove=e=>{if(e.pointerId!==cid)return;const dx=e.clientX-last[0],dy=e.clientY-last[1];yaw-=dx*.005;pitch=THREE.MathUtils.clamp(pitch+dy*.004,-.3,1.05);last=[e.clientX,e.clientY]};renderer.domElement.onpointerup=renderer.domElement.onpointercancel=e=>{if(e.pointerId===cid)cid=null};
$('#fs').onclick=async()=>{try{if(!document.fullscreenElement)await document.documentElement.requestFullscreen();else await document.exitFullscreen();try{await screen.orientation?.lock?.('landscape')}catch{}}catch{}};
