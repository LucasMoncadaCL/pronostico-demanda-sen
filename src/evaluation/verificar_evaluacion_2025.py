"""Independent, pre-aggregated integrity check for frozen 2025 outputs."""
from __future__ import annotations
import csv, hashlib, json
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import sys

REPO=Path(__file__).resolve().parents[2]
AUDITS=REPO/'data/audits'
OUT=AUDITS/'2025-demanda-sistemica/evaluacion-benchmark-congelada'
EVENTS={date(2025,2,25),date(2025,2,26)}
MIN_N=5

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
def read_rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        return [{'date':date.fromisoformat(r['fecha']),'hour':int(r['hora']),'value':Decimal(r['demanda'])} for r in csv.DictReader(f)]
def read_preds(path):
    with path.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def stats(history):
    wp=defaultdict(lambda:[Decimal(0),0]); h=defaultdict(lambda:[Decimal(0),0]); w=defaultdict(lambda:[Decimal(0),0]); total=[Decimal(0),0]
    for r in history:
        dow=r['date'].weekday(); hour=r['hour']; val=r['value']
        wp[(dow,hour)][0]+=val; wp[(dow,hour)][1]+=1
        h[hour][0]+=val; h[hour][1]+=1
        w[dow][0]+=val; w[dow][1]+=1
        total[0]+=val; total[1]+=1
    return wp,h,w,total
def expected(dow,hour,s):
    wp,h,w,total=s
    for level, pair in [('weekday_x_period',wp.get((dow,hour),(Decimal(0),0))),('period_all_weekdays',h.get(hour,(Decimal(0),0))),('weekday_all_periods',w.get(dow,(Decimal(0),0))),('global_all_periods',total)]:
        sm,n=pair
        if n>=MIN_N: return sm/Decimal(n),level,n
    return None,'no_support',0

def main():
    train=[r for r in read_rows(AUDITS/'2024-demanda-sistemica/serie_horaria_2024.csv') if r['date'].year==2024]
    target=read_rows(AUDITS/'2025-demanda-sistemica/serie_horaria_2025.csv')
    target_map={(r['date'],r['hour']):r['value'] for r in target}
    snapshot=[r for r in train if r['date']<date(2024,11,1)]
    all_history=train+target
    summary=json.loads((OUT/'evaluacion-benchmark-2025.json').read_text(encoding='utf-8'))
    checks={}
    for policy,filename in [('primary_60d_fixed_2024','predicciones-benchmark-2025-regimen-principal.csv'),('sensitivity_no_lag_updated_history','predicciones-benchmark-2025-sensibilidad.csv')]:
        rows=read_preds(OUT/filename); keys=[]; by_day=defaultdict(list)
        for r in rows: by_day[date.fromisoformat(r['target_date'])].append(r)
        assert len(rows)==8760
        for target_date in sorted(by_day):
            issue=target_date-timedelta(days=1); cutoff=issue-timedelta(days=60) if policy.startswith('primary') else issue
            history=snapshot if policy.startswith('primary') else [x for x in all_history if x['date']<issue]
            assert history and max(x['date'] for x in history)<cutoff
            s=stats(history)
            for r in by_day[target_date]:
                hour=int(r['target_period_index']); key=(target_date,hour); keys.append(key)
                assert key in target_map and Decimal(r['observed'])==target_map[key]
                assert date.fromisoformat(r['issue_date_local'])==issue
                assert date.fromisoformat(r['cutoff_date_exclusive'])==cutoff
                assert int(r['history_records'])==len(history)
                assert date.fromisoformat(r['history_start_date'])==min(x['date'] for x in history)
                assert date.fromisoformat(r['history_end_date'])==max(x['date'] for x in history)
                pred,level,n=expected(target_date.weekday(),hour,s)
                assert pred is not None and Decimal(r['prediction'])==pred and r['fallback_level']==level and int(r['n_support'])==n
                event=target_date in EVENTS
                assert r['event_window_2025_02_25_26']==str(event)
        assert len(keys)==len(set(keys))==8760 and set(keys)==set(target_map)
        checks[policy]={'rows':len(rows),'unique_targets':len(set(keys)),'predictions_recomputed_from_allowed_history':len(rows),'no_missing_targets':True,'cutoff_and_snapshot_checks':'pass'}
    mapping={
      'protocol_v1_2':REPO/'docs/protocol/protocolo-evaluacion-v1.2.md',
      'evaluation_script':REPO/'src/evaluation/evaluar_benchmark_2025.py',
      'baseline_implementation':REPO/'src/baselines/weekday_period_mean.py',
      'availability_policy_implementation':REPO/'src/evaluation/benchmark_policy.py',
      '2024_development_validation_script':REPO/'src/evaluation/validar_benchmark_2024.py',
      '2024_independent_verifier':REPO/'src/evaluation/verify_benchmark_predictions_2024.py',
      'unit_test_weekday_period':REPO/'tests/test_weekday_period_mean.py',
      'unit_test_availability_policy':REPO/'tests/test_benchmark_policy.py',
      'unit_test_frozen_evaluation':REPO/'tests/test_frozen_evaluation.py',
      '2024_validation_predictions':AUDITS/'2024-demanda-sistemica/benchmark-validacion-2024/predicciones-benchmark-2024.csv',
      '2024_validation_summary':AUDITS/'2024-demanda-sistemica/benchmark-validacion-2024/resumen-validacion-benchmark-2024.json'}
    for key,path in mapping.items(): assert sha(path)==summary['frozen_artifacts_sha256'][key],f'hash mismatch: {key}'
    assert sha(AUDITS/'2024-demanda-sistemica/serie_horaria_2024.csv')==summary['data']['train_2024_csv_sha256']
    assert sha(AUDITS/'2025-demanda-sistemica/serie_horaria_2025.csv')==summary['data']['target_2025_csv_sha256']
    assert sha(REPO/'docs/protocol/protocolo-evaluacion-v1.2.md')==summary['data']['protocol_sha256']
    print(json.dumps({'policies':checks,'frozen_hashes':'all matched','result':'PASS'},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
