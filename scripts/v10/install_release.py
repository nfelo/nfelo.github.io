#!/usr/bin/env python3
"""Install the embedded club update through GitHub without a large Git push."""
import argparse,base64,hashlib,io,json,subprocess,sys,time,zipfile
from pathlib import Path
REPO='nfelo/nfelo.github.io'
PAYLOAD=''
PAYLOAD_SHA256=''

def gh(*args,payload=None):
 command=['gh',*args]
 if payload is not None:command+=['--input','-']
 result=subprocess.run(command,input=None if payload is None else json.dumps(payload),text=True,capture_output=True)
 if result.returncode:raise RuntimeError(result.stderr.strip() or 'GitHub command failed')
 return result.stdout

def api(path,method='GET',payload=None):
 return json.loads(gh('api','--hostname','github.com','--method',method,f'repos/{REPO}'+('/'+path if path else ''),payload=payload) or '{}')

def load_payload():
 raw=base64.b64decode(PAYLOAD)
 if hashlib.sha256(raw).hexdigest()!=PAYLOAD_SHA256:raise ValueError('Installer payload checksum differs')
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  manifest=json.loads(z.read('manifest.json'));files={p:z.read(p) for p in manifest['files']}
 for name,body in files.items():
  if name.startswith('/') or '..' in Path(name).parts:raise ValueError('Unsafe release path')
  if hashlib.sha256(body).hexdigest()!=manifest['files'][name]['sha256']:raise ValueError('File checksum differs: '+name)
 return manifest,files

def install(manifest,files):
 metadata=api('');branch=metadata['default_branch']
 if branch!='main':raise RuntimeError('Expected default branch main; repository changed')
 parent=api('git/ref/heads/main')['object']['sha'];commit=api('git/commits/'+parent)
 tree=api('git/trees/'+commit['tree']['sha']+'?recursive=1')
 if tree.get('truncated'):raise RuntimeError('GitHub returned an incomplete file tree')
 existing={x['path']:x['sha'] for x in tree['tree'] if x['type']=='blob'};updates=[]
 for name,body in files.items():
  target=hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()
  if existing.get(name)==target:continue
  if existing.get(name)!=manifest['files'][name]['base_blob']:raise RuntimeError('Repository code changed since this release: '+name+'. No branch was changed. Reconcile this file before installing.')
  updates.append((name,body))
 print(f'Checked {len(files)} release files; {len(updates)} need updating.',flush=True)
 if updates:
  elements=[]
  for i,(name,body) in enumerate(updates,1):
   blob=api('git/blobs','POST',{'content':base64.b64encode(body).decode(),'encoding':'base64'});elements.append({'path':name,'mode':'100644','type':'blob','sha':blob['sha']})
   print(f'Uploaded {i}/{len(updates)}: {name}',flush=True)
  tree=api('git/trees','POST',{'base_tree':commit['tree']['sha'],'tree':elements})
  result=api('git/commits','POST',{'message':'Fix club updates, rating publication and source coverage [skip ci]','tree':tree['sha'],'parents':[parent]})
  if api('git/ref/heads/main')['object']['sha']!=parent:raise RuntimeError('main advanced during installation. No branch was changed. Run this same script again; it will preserve the new data.')
  api('git/refs/heads/main','PATCH',{'sha':result['sha'],'force':False})
  print('Installed commit: https://github.com/'+REPO+'/commit/'+result['sha'],flush=True)
 else:print('This release is already installed.',flush=True)
 gh('variable','set','V10_CLUBS_ENABLED','--body','true','--repo',REPO)
 for attempt in range(5):
  try:gh('workflow','run','v10-clubs.yml','--repo',REPO,'--ref','main');break
  except RuntimeError:
   if attempt==4:raise
   time.sleep(3)
 print('\nUpdate started. GitHub now rebuilds and publishes the club section.\nProgress: https://github.com/'+REPO+'/actions/workflows/v10-clubs.yml\nThe schedule continues automatically three times a day.\nCoverage gaps and cross-era peak limitations remain documented on the site.',flush=True)

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--extract',type=Path,help='Extract and verify files without changing GitHub');args=parser.parse_args();manifest,files=load_payload()
 if args.extract:
  args.extract.mkdir(parents=True,exist_ok=True)
  for name,body in files.items():
   p=args.extract/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
  (args.extract/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(f'Verified and extracted {len(files)} files. No GitHub changes.');return
 install(manifest,files)
if __name__=='__main__':
 try:main()
 except (RuntimeError,ValueError) as error:print('Installation stopped: '+str(error),file=sys.stderr);sys.exit(1)
