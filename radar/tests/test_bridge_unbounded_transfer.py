"""Synthetic byte-transfer acceptance, never a real provider/model invocation."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
import hashlib
import json
import tempfile
import time
import unittest
from urllib.error import HTTPError

from crt_radar import gpt_transport_worker as worker
from crt_radar.gpt_bridge_outbox import (canonical_bytes, encode_evidence_references,
    expand_evidence_references, build_transfer_manifest, receive_transfer_part, reassemble_transfer,
    enqueue_bridge_payload)
from crt_radar.gpt_handoff import (build_minimized_bridge_payload, expand_bridge_field_names,
    run_gpt_handoff_gate, _bridge_market_context)
from crt_radar.openai_responses_adapter_contract import build_request_envelope, SMOKE_MODEL
from crt_radar.plain_language_notice import build_plain_language_notice
from test_gpt_handoff import bridge_pack, pack
from test_openai_responses_adapter_contract import response


def source(marker='A', **updates):
    return dict(source_id='SYNTHETIC-'+marker,asset_id='ASST',observed_at_ms=100,
        retrieved_at_ms=101,quality_state='RESEARCH_ONLY',version='V1',
        values='synthetic research detail '*100,**updates)


class HTTPResult:
    status=200
    def __init__(self,raw):self.raw=raw
    def read(self,n):return self.raw[:n]
    def __enter__(self):return self
    def __exit__(self,*args):pass


class PartsService:
    """Mock of documented Uploads/Files/Responses HTTP, verifies actual bytes."""
    def __init__(self):
        self.parts={};self.files={};self.requests=[];self.inferences=0
        self.fail_after=None;self.corrupt_download=False;self.completed_raw=None
        self.reject_inline=False;self.max_part_request=None;self.lost_complete_once=False
        self.complete_was_lost=False;self.reject_recomplete=False;self.inference_timeout=False
        self.file_missing_once=False
    def open(self,request,timeout):
        path=request.full_url.removeprefix('https://api.openai.com')
        self.requests.append((path,request.data))
        if path=='/v1/uploads':
            self.create=json.loads(request.data)
            result={'id':'upload_synthetic','expires_at':int(time.time())+3600}
        elif path.endswith('/parts'):
            if self.max_part_request and len(request.data)>self.max_part_request:
                raise HTTPError(request.full_url,413,'synthetic',None,None)
            if self.fail_after is not None and len(self.parts)>=self.fail_after:
                raise TimeoutError('synthetic interruption before part acceptance')
            raw=request.data.split(b'\r\n\r\n',1)[1].rsplit(b'\r\n--',1)[0]
            identity='part_'+str(len(self.parts));self.parts[identity]=raw
            result={'id':identity,'upload_id':'upload_synthetic'}
        elif path.endswith('/complete'):
            if self.complete_was_lost and self.reject_recomplete:
                raise HTTPError(request.full_url,400,'already completed',None,None)
            body=json.loads(request.data)
            self.completed_raw=b''.join(self.parts[i] for i in body['part_ids'])
            assert hashlib.md5(self.completed_raw,usedforsecurity=False).hexdigest()==body['md5']
            assert len(self.completed_raw)==self.create['bytes']
            self.files['file-synthetic']=self.completed_raw
            if self.lost_complete_once:
                self.lost_complete_once=False
                self.complete_was_lost=True
                raise TimeoutError('synthetic lost completion acknowledgement')
            result={'id':'upload_synthetic','status':'completed','file':{'id':'file-synthetic'}}
        elif path.endswith('/content'):
            if self.file_missing_once:
                self.file_missing_once=False
                raise HTTPError(request.full_url,404,'synthetic expired file',None,None)
            raw=self.files['file-synthetic']
            return HTTPResult(raw+b'!' if self.corrupt_download else raw)
        elif path=='/v1/files?purpose=assistants&limit=100&order=desc':
            result={'data':[{'id':identity,'filename':self.create['filename'],'bytes':len(data)} for identity,data in self.files.items()]}
        elif path=='/v1/responses':
            body=json.loads(request.data)
            if isinstance(body['input'],str) and self.reject_inline:
                raise HTTPError(request.full_url,413,'synthetic',None,None)
            if isinstance(body['input'],list):
                file_id=body['input'][0]['content'][0]['file_id']
                assert self.files[file_id]==self.completed_raw
            self.inferences+=1
            if self.inference_timeout:raise TimeoutError('synthetic ambiguous inference outcome')
            result=response()
        else:raise AssertionError(path)
        return HTTPResult(canonical_bytes(result))


def large_bridge(root, size):
    evidence=bridge_pack(pack(evidence_hash='d'*64,requested=True))
    evidence['changes']={'retained_history':source()|{'values':'v'*size}}
    handoff=run_gpt_handoff_gate(evidence,build_plain_language_notice(evidence),ledger_path=root/'handoff.jsonl')
    return evidence,build_minimized_bridge_payload(evidence,handoff)


class UnboundedBridgeTests(unittest.TestCase):
    def test_exact_identity_and_content_share_once_with_lossless_restore(self):
        fact=source(); original={'first':fact,'nested':{'same':deepcopy(fact)},'history':[deepcopy(fact)]}
        wire=encode_evidence_references(original)
        self.assertLess(len(canonical_bytes(wire)),len(canonical_bytes(original)))
        self.assertEqual(len(wire['evidence_reference_encoding']['objects']),1)
        self.assertEqual(expand_evidence_references(json.loads(canonical_bytes(wire))),original)

    def test_small_exact_evidence_also_has_one_canonical_copy(self):
        fact={'source_id':'OFFLINE','asset_id':'BTC','as_of_ms':123,'quality_state':'RESEARCH_ONLY','value':1}
        original={'first':fact,'second':deepcopy(fact)}
        wire=encode_evidence_references(original)
        self.assertEqual(len(wire['evidence_reference_encoding']['objects']),1)
        self.assertEqual(expand_evidence_references(wire),original)

    def test_equal_values_different_dates_sources_versions_quality_are_not_coalesced(self):
        base=source(); rows=[base]
        for key,value in [('observed_at_ms',102),('source_id','OTHER'),('version','V2'),
                          ('quality_state','BLOCKED'),('asset_id','MSTR')]:
            row=deepcopy(base);row[key]=value;rows.append(row)
        original={'facts':rows};wire=encode_evidence_references(original)
        self.assertNotIn('evidence_reference_encoding',wire)
        self.assertEqual(expand_evidence_references(wire),original)

    def test_inherited_identity_prevents_equal_child_content_from_merging(self):
        child={'details':'research '*400}
        original={'a':{'source_id':'A','observed_at_ms':1,'data':child},
                  'b':{'source_id':'B','observed_at_ms':2,'data':deepcopy(child)}}
        self.assertNotIn('evidence_reference_encoding',encode_evidence_references(original))

    def test_reference_tamper_missing_and_cycles_fail_closed(self):
        wire=encode_evidence_references({'a':source(),'b':source()})
        codec=wire['evidence_reference_encoding'];key=next(iter(codec['objects']))
        for action in ('modify','missing','cycle'):
            bad=deepcopy(wire);objects=bad['evidence_reference_encoding']['objects']
            if action=='modify':objects[key]['value']['quality_state']='VALID'
            elif action=='missing':objects.pop(key)
            else:objects[key]['value']={'$crt_evidence_ref':key}
            with self.assertRaises(ValueError):expand_evidence_references(bad)

    def test_16k_64k_1m_unique_evidence_is_never_omitted(self):
        for size in (17*1024,65*1024,1024*1024):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as directory:
                evidence,wire=large_bridge(Path(directory),size)
                expanded=expand_bridge_field_names(wire)
                self.assertEqual(expanded['market_context'],_bridge_market_context(evidence))
                envelope=build_request_envelope(wire,model=SMOKE_MODEL)
                self.assertGreater(len(envelope['request_body']['input'].encode()),size)
                self.assertFalse(wire['authority']['machine_may_execute_trade'])

    def test_manifest_order_hash_missing_corruption_and_cas_dedup(self):
        raw=b'a'*1000+b'b'*1000+b'a'*1000
        manifest,chunks=build_transfer_manifest(raw,part_bytes=1000)
        self.assertEqual(len(chunks),2)
        with tempfile.TemporaryDirectory() as directory:
            for digest,data in chunks.items():receive_transfer_part(directory,manifest,digest,data)
            self.assertEqual(len(list((Path(directory)/'parts').iterdir())),2)
            self.assertEqual(reassemble_transfer(directory,manifest),raw)
            bad=deepcopy(manifest);bad['parts'].reverse()
            with self.assertRaises(ValueError):reassemble_transfer(directory,bad)
            part=Path(directory)/'parts'/(manifest['parts'][0]['sha256']+'.bin')
            part.write_bytes(b'bad')
            with self.assertRaises(ValueError):reassemble_transfer(directory,manifest)
            part.unlink()
            with self.assertRaises(FileNotFoundError):reassemble_transfer(directory,manifest)

    def test_provider_parts_reassemble_over_16k_64k_and_1m(self):
        for size in (17*1024,65*1024,1024*1024):
            with self.subTest(size=size),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);_,wire=large_bridge(root,size)
                env=build_request_envelope(wire,model=SMOKE_MODEL);server=PartsService()
                with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(worker.urlrequest,'build_opener',return_value=server):
                    result=worker._post_response(env,transfer_root=root/'transfer',force_upload=True)
                self.assertEqual(result,response());self.assertEqual(server.inferences,1)
                self.assertEqual(server.completed_raw,env['request_body']['input'].encode())
                journals=list((root/'transfer').glob('*.json'))
                self.assertEqual(json.loads(journals[0].read_text())['remote_sha256_verified'],hashlib.sha256(server.completed_raw).hexdigest())

    def test_interrupted_worker_retains_pending_and_resumes_missing_parts_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,wire=large_bridge(root,1024*1024)
            enqueue_bridge_payload(root/'outbox',wire);event=wire['event']['event_id']
            server=PartsService();server.fail_after=2
            with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(worker.urlrequest,'build_opener',return_value=server):
                first=worker.deliver_event(root/'outbox'/(event+'.json'),root/'state')
                self.assertEqual(first['state'],'INPUT_TRANSFER_PENDING');self.assertEqual(server.inferences,0)
                self.assertEqual(first['input_transfer_state'],'PENDING')
                self.assertFalse(first['notification_eligible'])
                saved=json.loads((root/'state'/(event+'.json')).read_text())
                self.assertNotIn('request_hash',saved);self.assertIsNone(saved['receipt'])
                accepted=dict(server.parts);server.fail_after=None
                second=worker.deliver_event(root/'outbox'/(event+'.json'),root/'state')
                self.assertEqual(second['state'],'DELIVERED');self.assertEqual(server.inferences,1)
                self.assertEqual({k:server.parts[k] for k in accepted},accepted)
                expected=(len(server.completed_raw)+worker.UPLOAD_PART_BYTES-1)//worker.UPLOAD_PART_BYTES
                self.assertEqual(len(server.parts),expected)
                self.assertEqual(worker.deliver_event(root/'outbox'/(event+'.json'),root/'state')['state'],'ALREADY_DELIVERED')
                self.assertEqual(server.inferences,1)
            self.assertFalse((root/'state'/'notifications').exists())

    def test_remote_corruption_never_starts_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,wire=large_bridge(root,65*1024);server=PartsService();server.corrupt_download=True
            with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(worker.urlrequest,'build_opener',return_value=server):
                with self.assertRaises(worker.InputTransferPending):worker._post_response(build_request_envelope(wire,model=SMOKE_MODEL),transfer_root=root/'parts')
            self.assertEqual(server.inferences,0)

    def test_physical_part_limit_adapts_without_losing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,wire=large_bridge(root,65*1024);server=PartsService();server.max_part_request=16*1024
            env=build_request_envelope(wire,model=SMOKE_MODEL)
            with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(worker.urlrequest,'build_opener',return_value=server):
                worker._post_response(env,transfer_root=root/'parts')
            self.assertEqual(server.completed_raw,env['request_body']['input'].encode());self.assertEqual(server.inferences,1)

    def test_inline_413_routes_to_parts_without_second_model_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,wire=large_bridge(root,17*1024);server=PartsService();server.reject_inline=True
            with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(worker.urlrequest,'build_opener',return_value=server):
                worker._post_response(build_request_envelope(wire,model=SMOKE_MODEL),transfer_root=root/'parts')
            self.assertEqual(server.inferences,1);self.assertIsNotNone(server.completed_raw)

    def test_lost_complete_ack_retries_input_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,wire=large_bridge(root,65*1024);server=PartsService();server.lost_complete_once=True
            with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(worker.urlrequest,'build_opener',return_value=server):
                worker._post_response(build_request_envelope(wire,model=SMOKE_MODEL),transfer_root=root/'parts')
            self.assertEqual(server.inferences,1)

    def test_completion_already_committed_is_reconciled_by_downloaded_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,wire=large_bridge(root,65*1024);server=PartsService()
            server.lost_complete_once=True;server.reject_recomplete=True
            with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(worker.urlrequest,'build_opener',return_value=server):
                worker._post_response(build_request_envelope(wire,model=SMOKE_MODEL),transfer_root=root/'parts')
            self.assertEqual(server.inferences,1)
            self.assertTrue(any('/v1/files?' in p for p,_ in server.requests))

    def test_ambiguous_inference_is_not_replayed_after_successful_parts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,wire=large_bridge(root,65*1024);server=PartsService();server.inference_timeout=True
            enqueue_bridge_payload(root/'outbox',wire);path=root/'outbox'/(wire['event']['event_id']+'.json')
            with patch.dict('os.environ',{'OPENAI_API_KEY':'test-only'}),patch.object(worker.urlrequest,'build_opener',return_value=server):
                self.assertEqual(worker.deliver_event(path,root/'state')['state'],'RECONCILIATION_REQUIRED')
                before=len(server.requests)
                self.assertEqual(worker.deliver_event(path,root/'state')['state'],'RECONCILIATION_REQUIRED')
                self.assertEqual(len(server.requests),before)
            self.assertEqual(server.inferences,1)

    def test_large_strings_keep_secret_email_and_private_path_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            _,wire=large_bridge(Path(directory),1024*1024)
            worker.validate_transport_payload(wire)
            for forbidden in ('private@example.test','sk-'+'A'*30,'C:/Users/private/secret'):
                bad=deepcopy(wire);bad['market_context']['audit']='v'*100000+' '+forbidden
                bad.pop('bridge_payload_hash');bad['bridge_payload_hash']=hashlib.sha256(canonical_bytes(bad)).hexdigest()
                with self.assertRaises(ValueError):worker.validate_transport_payload(bad)

    def test_old_v01_receipt_replays_original_request_without_new_inference(self):
        from crt_radar.openai_responses_adapter_contract import (LEGACY_CONTRACT_VERSION,
            build_instructions,validate_request_envelope,build_delivery_receipt)
        from crt_radar.gpt_transport_boundary import (ensure_pending_boundary_state,claim_delivery,
            mark_delivered,persist_boundary_state,_read_json,_write_no_clobber)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,wire=large_bridge(root,0)
            old=build_request_envelope(wire,model=SMOKE_MODEL)
            old['contract_version']=LEGACY_CONTRACT_VERSION
            old['smoke_guardrails']['max_input_utf8_bytes']=16*1024
            old['request_body']['instructions']=build_instructions(legacy=True)
            old.pop('request_hash');old['request_hash']=hashlib.sha256(canonical_bytes(old)).hexdigest()
            validate_request_envelope(old)
            event=wire['event']['event_id'];state_root=root/'states'
            enqueue_bridge_payload(root/'outbox',wire)
            ensure_pending_boundary_state(state_root,wire)
            state=_read_json(state_root/(event+'.json'))
            state=claim_delivery(state,adapter_id=worker.ADAPTER_ID,now_ms=1,lease_ms=100,adapter_selected=True)
            receipt=build_delivery_receipt(response(),event_id=event,bridge_payload_hash=wire['bridge_payload_hash'],request_hash=old['request_hash'])
            state=mark_delivered(state,claim_token=state['claim']['claim_token'],receipt=receipt)
            persist_boundary_state(state_root,state)
            saved=state_root/'responses'/(event+'.json')
            _write_no_clobber(saved,{'request':old,'response':response()});original=saved.read_bytes()
            transport=Mock()
            result=worker.deliver_event(root/'outbox'/(event+'.json'),state_root,transport=transport,now_ms=200)
            self.assertEqual(result['state'],'ALREADY_DELIVERED');transport.assert_not_called()
            self.assertEqual(saved.read_bytes(),original)

    def test_capital_claim_catalog_resolves_refs_without_promoting_codec_metadata(self):
        from crt_radar.capital_decision_closure import semantic_evidence_catalog,text
        from test_capital_decision_closure import source_fixture,NOW
        from crt_radar.capital_decision_closure import build_projection,build_source
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,wire=large_bridge(root,0)
            at=wire['market_context']['generated_at_ms']
            source_data=source_fixture(wire,at)
            projection=build_projection(wire,source_data,at_ms=at)
            fact=source()|{'asset':'ASST','value':12.5,'as_of_ms':100}
            projection['market_context']['same_evidence']={'a':fact,'b':deepcopy(fact)}
            expected=semantic_evidence_catalog(projection)
            projection['market_context']=encode_evidence_references(projection['market_context'])
            actual=semantic_evidence_catalog(projection)
            self.assertEqual(actual,expected)
            self.assertFalse(any('evidence_reference_encoding' in path for path in actual))
            self.assertFalse(any('$crt_evidence_ref' in path for path in actual))
        text('v'*(1024*1024))
        with self.assertRaises(ValueError):text('v'*100000+' private@example.test')

    def test_expired_uploaded_file_is_replaced_without_losing_source_or_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);raw=b'preserved input '*10000;server=PartsService()
            worker._upload_response_input(raw,opener=server,key='test-only',root=root)
            server.file_missing_once=True
            worker._upload_response_input(raw,opener=server,key='test-only',root=root)
            journal=json.loads(next(root.glob('*.json')).read_text(encoding='utf-8'))
            self.assertEqual(server.completed_raw,raw);self.assertEqual(server.inferences,0)
            self.assertTrue(journal['attempt_history'])
            self.assertEqual(journal['remote_sha256_verified'],hashlib.sha256(raw).hexdigest())


if __name__=='__main__':unittest.main()
