'use strict';
// Run with: node --test tests_local/test_frontend_navigation.js
const test = require('node:test');
const assert = require('node:assert/strict');
const {parseRoute, routeURL, handleProfileFormChange, withDisabledControls, acceptConfigSnapshot} = require('../local_app/static/app.js');

test('unknown views and script-shaped values fall back to the workbench', () => {
  for (const search of ['', '?view=missing', '?view=javascript%3Aalert(1)', '?view=__proto__', '?view=constructor']) {
    assert.deepEqual(parseRoute(search), {view:'home'});
  }
});

test('only recognized view parameters survive normalization', () => {
  const input = '?view=model-edit&profile=connection_1&api_key=synthetic-do-not-store&base_url=https://private.invalid&prompt=private-text';
  assert.equal(routeURL(parseRoute(input)), '?view=model-edit&profile=connection_1');
  assert.equal(routeURL({view:'models', profile:'ignored-profile', topic:'key', api_key:'synthetic-do-not-store'}), '?view=models');
});

test('editing requires a bounded server-compatible profile identifier', () => {
  for (const value of ['', '../secret', '<script>', 'a'.repeat(65)]) {
    assert.deepEqual(parseRoute('?view=model-edit&profile='+encodeURIComponent(value)), {view:'models'});
  }
  for (const value of ['a', 'abc_123-DEF', 'a'.repeat(64)]) {
    assert.deepEqual(parseRoute('?view=model-edit&profile='+value), {view:'model-edit',profile:value});
  }
});

test('routing view does not require a profile and strips invalid context', () => {
  assert.deepEqual(parseRoute('?view=model-routing'), {view:'model-routing'});
  assert.deepEqual(parseRoute('?view=model-routing&profile=../bad'), {view:'model-routing'});
  assert.deepEqual(parseRoute('?view=model-routing&profile=abc'), {view:'model-routing',profile:'abc'});
});

test('help topics use an allowlist and never interpolate unknown topic text', () => {
  assert.deepEqual(parseRoute('?view=help&topic=key'), {view:'help',topic:'key'});
  assert.deepEqual(parseRoute('?view=help&topic=__proto__'), {view:'help'});
  assert.deepEqual(parseRoute('?view=help&topic=synthetic-secret'), {view:'help'});
});

test('refreshable links round-trip all page and contextual help destinations', () => {
  const routes = ['home','tasks','models','model-new','model-routing','help'].map(view=>({view}));
  routes.push({view:'model-edit',profile:'saved_connection'}, {view:'model-routing',profile:'saved_connection'});
  for (const topic of ['saved','workflow','base-url','qwen','model-id','key','capabilities','host','gateway']) routes.push({view:'help',topic});
  for (const route of routes) assert.deepEqual(parseRoute(routeURL(route)), route);
});


test('billing select input cannot overwrite the choice before its change handler runs', () => {
  let selectedEntry = 'token_plan';
  let baseURL = 'standard';
  let genericRefreshes = 0;
  const actions = {
    markDirty() {},
    updateCapabilities() { genericRefreshes += 1; selectedEntry = baseURL; },
    updateThinking() {}
  };
  // Native <select>: selection changes, input bubbles, then change is emitted.
  handleProfileFormChange({type:'input',target:{id:'provider-option'}},actions);
  baseURL = selectedEntry; // Dedicated billing handler reads the still-intact choice.
  handleProfileFormChange({type:'change',target:{id:'provider-option'}},actions);
  assert.equal(baseURL, 'token_plan');
  assert.equal(selectedEntry, 'token_plan');
  assert.equal(genericRefreshes, 0);
});

test('ordinary edits still mark the draft and refresh dependent capability controls', () => {
  const calls = [];
  const actions = {
    markDirty() { calls.push('dirty'); },
    updateCapabilities() { calls.push('capabilities'); },
    updateThinking() { calls.push('thinking'); }
  };
  handleProfileFormChange({type:'input',target:{id:'model-id'}},actions);
  assert.deepEqual(calls, ['dirty','capabilities','thinking']);
  calls.length = 0;
  handleProfileFormChange({type:'change',target:{id:'test-capability'}},actions);
  assert.deepEqual(calls, []); // Merely selecting what to test is not a model edit.
});


test('a delayed model save locks all controls until the response and restores prior disabled states', async () => {
  const controls = [{disabled:false}, {disabled:true}, {disabled:false}];
  let finish;
  const response = new Promise(resolve => { finish = resolve; });
  const pending = withDisabledControls(controls, () => response);
  assert.deepEqual(controls.map(item=>item.disabled), [true,true,true]);
  await Promise.resolve();
  assert.deepEqual(controls.map(item=>item.disabled), [true,true,true]);
  finish('saved');
  assert.equal(await pending, 'saved');
  assert.deepEqual(controls.map(item=>item.disabled), [false,true,false]);
});

test('a failed model save unlocks the form without changing its draft values', async () => {
  const controls = [{disabled:false,value:'draft'}, {disabled:true,value:'synthetic-not-a-real-key'}];
  await assert.rejects(withDisabledControls(controls, async () => { throw new Error('controlled failure'); }), /controlled failure/);
  assert.deepEqual(controls, [{disabled:false,value:'draft'}, {disabled:true,value:'synthetic-not-a-real-key'}]);
});


test('an earlier GET resolving after a save cannot remove the newly saved connection', async () => {
  let releaseOldRead;
  let current = {revision:1, profiles:[{id:'existing'}]};
  const oldRead = new Promise(resolve => { releaseOldRead = resolve; });
  const pendingRead = oldRead.then(value => { current = acceptConfigSnapshot(current,value); });
  current = acceptConfigSnapshot(current,{config:{revision:2, profiles:[{id:'existing'},{id:'just-saved'}]}});
  releaseOldRead({revision:1, profiles:[{id:'existing'}]});
  await pendingRead;
  assert.equal(current.revision, 2);
  assert.deepEqual(current.profiles.map(profile=>profile.id), ['existing','just-saved']);
});

test('stale responses cannot revert routing or resurrect a deleted connection', async () => {
  let releaseOldRead;
  let current = {revision:4, generation_mode:'host', profiles:[{id:'removed'}]};
  const pendingRead = new Promise(resolve => { releaseOldRead = resolve; }).then(value => {
    current = acceptConfigSnapshot(current,value);
  });
  current = acceptConfigSnapshot(current,{revision:5,generation_mode:'independent',profiles:[]});
  releaseOldRead({config:{revision:4,generation_mode:'host',profiles:[{id:'removed'}]}});
  await pendingRead;
  assert.equal(current.generation_mode, 'independent');
  assert.deepEqual(current.profiles, []);
});

test('equal revision refreshes remain available for test and credential status updates', () => {
  const current = {revision:5,profiles:[{id:'saved',test_status:'untested'}]};
  const latestStatus = {revision:5,profiles:[{id:'saved',test_status:'passed'}]};
  assert.equal(acceptConfigSnapshot(current, latestStatus), latestStatus);
  assert.equal(acceptConfigSnapshot(current, {profiles:[]}), current);
  assert.equal(acceptConfigSnapshot(null, current), current);
});
