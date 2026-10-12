"""Provider-shaped synthetic mechanics; never evidence of real dataset readiness."""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
import l6_public_capture as capture
from crt_radar import l6_source_binding as l6


def zipped(name, content):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as archive:
        archive.writestr(zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0)),content)
    return output.getvalue()


class L6PublicCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'new-capture'
        self.end=int(time.time()*1000)//l6.DAY*l6.DAY
        self.calls=[]
        self.authority=l6.lock()
        self.kraken_doc=next(v['documentation'] for v in self.authority['decisions'][l6.COMPOSITE]['venue_universe'] if v['venue_id']=='KRAKEN_XBT_USD')
        self.archive='https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_2026Q2.zip'
        self.kraken_missing=False
        self.bad_checksum=False
        self.coinbase_error=False
        self.boundary_gap=False

    def raw(self,url):
        if url==self.kraken_doc:
            return f'<a href="{self.archive}">official</a><a href="https://evil.invalid/foreign.zip">not official</a>'.encode()
        rows=[]
        for index in range(201):
            t=(self.end-(201-index)*l6.DAY)//1000
            price=100+index
            rows.append((t,price,price+10,price-5,price+3,50))
        if 'coinbase.com' in url:
            if self.coinbase_error:raise OSError('OFFLINE_TEST_FAILURE')
            return json.dumps([[t,low,h,o,c,v] for t,o,h,low,c,v in rows]).encode()
        if 'bitstamp.net' in url:
            return json.dumps({'data':{'pair':'BTC/USD','ohlc':[dict(zip(('timestamp','open','high','low','close','volume'),r)) for r in rows]}}).encode()
        if url==self.archive:
            if self.kraken_missing:rows=rows[:-2]
            return zipped('XBTUSD_1440.csv','\n'.join(','.join(map(str,r))+',2' for r in rows))
        if url.endswith('.CHECKSUM'):
            archive_url=url[:-9]
            digest='0'*64 if self.bad_checksum else hashlib.sha256(self.raw(archive_url)).hexdigest()
            return f'{digest}  {Path(urlsplit(archive_url).path).name}\n'.encode()
        date=Path(urlsplit(url).path).name.removeprefix('BTCUSDT-aggTrades-').removesuffix('.zip')
        from datetime import datetime,timezone
        start=int(datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()*1000)
        index=(start-(self.end-22*l6.DAY))//l6.DAY
        identifier=index*2+(1 if self.boundary_gap and index==10 else 0)
        member=Path(urlsplit(url).path).name[:-4]+'.csv'
        return zipped(member,f'{identifier},10,3,{identifier},{identifier},{start*1000},false,true\n'
            f'{identifier+1},10,1,{identifier+1},{identifier+1},{start*1000+1000},true,true')

    def fetch(self,**kwargs):
        self.calls.append(kwargs['url'])
        return {'body':self.raw(kwargs['url']),'status_code':200,'final_url':kwargs['url'],
            'content_type':'application/octet-stream','retrieved_at_ms':int(time.time()*1000)}

    def run_capture(self):
        return capture.capture_sources(self.root,fetcher=self.fetch)

    def test_full_mechanics_use_original_store_and_existing_decision_chain(self):
        with patch('crt_radar.source_gate_runner._http_get',side_effect=AssertionError('UNAPPROVED_OTHER_SOURCE_FETCH')):
            result=self.run_capture()
        self.assertTrue(all(r['state']=='PASS' for r in result['qualification'].values()))
        self.assertEqual(result['qualification'][l6.COMPOSITE]['measurement_days'],201)
        self.assertEqual(result['qualification'][l6.AGGRESSOR]['measurement_days'],20)
        self.assertEqual(len(result['evidence_chain']['l6_metrics']),4)
        # Qualified L6 can support an existing research warning, never a formal
        # spring confirmation when institutional/leverage/veto inputs are absent.
        self.assertNotEqual(result['evidence_chain']['scenario_id'],'SCENARIO_1')
        self.assertIsNone(result['evidence_chain']['formal_season'])
        pack=json.loads((self.root/'verification/evidence_pack.json').read_text(encoding='utf-8'))
        self.assertEqual(pack['authority']['production'],'NOT_APPROVED')
        self.assertEqual(pack['authority']['capital_decision_authority'],'USER_ONLY')
        self.assertEqual(len(self.calls),len(set(self.calls)))
        self.assertEqual(result['request_count'],48)
        for family in l6.SOURCE_IDS:
            manifest=json.loads((self.root/f'{family}.json').read_text())
            for artifact in manifest['artifacts']:
                self.assertEqual(artifact['first_seen_at_ms'],artifact['retrieved_at_ms'])
                self.assertGreaterEqual(artifact['first_seen_at_ms'],self.end)
                self.assertEqual(hashlib.sha256(l6.read_artifact(self.root,artifact,result['evaluated_at_ms'])).hexdigest(),artifact['sha256'])

    def test_kraken_lag_blocks_composite_without_older_intersection(self):
        self.kraken_missing=True
        result=self.run_capture()
        self.assertEqual(result['qualification'][l6.COMPOSITE]['state'],'BLOCKED')
        self.assertIn('THREE_VENUE_DAY_MISSING',result['qualification'][l6.COMPOSITE]['reason'])
        self.assertEqual(result['venues']['KRAKEN_XBT_USD']['complete_days_in_window'],199)
        self.assertEqual(result['qualification'][l6.AGGRESSOR]['state'],'PASS')
        self.assertEqual(list(result['evidence_chain']['l6_metrics']),['cvd_20d_share'])
        self.assertEqual(result['evidence_chain']['scenario_id'],'SCENARIO_0')

    def test_missing_source_does_not_erase_other_verified_data_or_retry(self):
        self.coinbase_error=True
        result=self.run_capture()
        self.assertEqual(result['venues']['BITSTAMP_BTC_USD']['state'],'PASS')
        self.assertEqual(result['qualification'][l6.COMPOSITE]['state'],'BLOCKED')
        self.assertEqual(result['qualification'][l6.AGGRESSOR]['state'],'PASS')
        self.assertEqual(len(self.calls),len(set(self.calls)))

    def test_checksum_and_cross_day_boundary_fail_closed(self):
        for fault in ('bad_checksum','boundary_gap'):
            with self.subTest(fault=fault):
                self.root=Path(self.temp.name)/fault
                setattr(self,fault,True)
                result=self.run_capture()
                self.assertEqual(result['qualification'][l6.AGGRESSOR]['state'],'BLOCKED')
                self.assertNotIn('cvd_20d_share',result['evidence_chain']['l6_metrics'])
                setattr(self,fault,False)

    def test_existing_archive_is_not_rewritten(self):
        self.root.mkdir()
        marker=self.root/'private-state.json';marker.write_text('untouched')
        with self.assertRaises(FileExistsError):self.run_capture()
        self.assertEqual(marker.read_text(),'untouched')
        self.assertEqual(self.calls,[])

    def test_redirect_future_clock_and_non200_never_qualify(self):
        for mutation in ({'final_url':'https://evil.invalid/'},{'retrieved_at_ms':int(time.time()*1000)+l6.DAY}, {'status_code':206}):
            with self.subTest(mutation=mutation):
                root=Path(self.temp.name)/str(len(list(Path(self.temp.name).iterdir())))
                root.mkdir()
                def bad(**kw):return {**self.fetch(**kw),**mutation}
                client=capture.Capture(root,self.authority,fetcher=bad,max_archive_bytes=10)
                with self.assertRaises(l6.L6SourceError):client.get(self.kraken_doc,l6.COMPOSITE)
                self.assertEqual(list(root.iterdir()),[])

    def test_resource_limit_cannot_turn_truncated_bytes_into_an_archive(self):
        self.root.mkdir()
        def oversized(**kw):return {**self.fetch(**kw),'body':b'x'*11}
        client=capture.Capture(self.root,self.authority,fetcher=oversized,max_archive_bytes=10)
        client.archives.add(self.archive)
        with self.assertRaisesRegex(l6.L6SourceError,'BODY_INVALID'):
            client.get(self.archive,l6.COMPOSITE,archive=True)
        self.assertEqual(list(self.root.iterdir()),[])
        self.assertEqual(len(client.attempts),1)

    def test_unknown_venues_quarter_parts_and_nonlocked_endpoints_are_excluded(self):
        page=(f'<a href="{self.archive}">q</a><a href="{self.archive}.part00">part</a>'
              '<a href="https://evil.invalid/Kraken_OHLCVT_2026Q3.zip">bad</a>').encode()
        self.assertEqual(capture.quarterly_links(page),[self.archive])
        for url in ('https://api.kraken.com/0/public/OHLC','https://api.exchange.coinbase.com/products/ETH-USD/candles?granularity=86400',
                    'https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=60','http://data.binance.vision/test'):
            self.assertFalse(capture.request_allowed(url,self.kraken_doc,set()))

    def test_same_failed_identity_is_never_automatically_retried(self):
        self.root.mkdir();self.coinbase_error=True
        client=capture.Capture(self.root,self.authority,fetcher=self.fetch,max_archive_bytes=10)
        url='https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400'
        for _ in range(2):
            with self.assertRaises(OSError):client.get(url,l6.COMPOSITE)
        self.assertEqual(self.calls,[url])


if __name__=='__main__':unittest.main()
