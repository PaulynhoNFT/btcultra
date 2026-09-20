import test from 'node:test';
import assert from 'node:assert/strict';
import {chartBounds,zoneText} from '../src/lib/structure';
test('flat chart remains drawable',()=>{const b=chartBounds([{time:0,close_time:1,open:100,high:100,low:100,close:100}],[]); assert.ok(b.high>b.low);assert.ok(b.high>100 && b.low<100);});
test('chart includes the relevant region outside candle range',()=>{const b=chartBounds([{time:0,close_time:1,open:100,high:101,low:99,close:100}],[{kind:'retracement',side:'BULL',low:70,high:80,time:0,confirmed_at:1,status:'open',ended_at:null}]);assert.ok(b.low<70);});
test('filled gaps cannot be labelled unfilled',()=>{assert.equal(zoneText({kind:'gap',side:'BULL',low:1,high:2,time:0,confirmed_at:1,status:'filled',ended_at:3}),'Faixa já preenchida');});
