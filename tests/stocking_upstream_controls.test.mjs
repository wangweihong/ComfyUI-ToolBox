import {test} from 'node:test';
import assert from 'node:assert/strict';
import {nearestPath,claimPixels,MATERIAL_DEFAULTS,linkedSparklePatch} from '../web/js/stocking_upstream_controls.mjs';
test('pointer deletes the targeted path rather than last path',()=>{
    assert.equal(nearestPath([[[0,0],[100,0]],[[0,20],[100,20]]],[40,1],5),0);
    assert.equal(nearestPath([{points:[[2,2]]},{points:[[4,4],[8,8]]}],[2,2],1),0);
    assert.equal(nearestPath([[[0,0],[100,0]]],[30,10],5),-1);
});
test('claimed pixels clear competing paint and exclude an external mask',()=>{
    const paint=new Uint8ClampedArray([255,255,255,255,255,255,255,255]),erase=new Uint8ClampedArray(8);
    claimPixels(paint,erase,new Uint8Array([255,0]));
    assert.equal(paint[0],0);assert.equal(erase[0],255);assert.equal(paint[4],255);assert.equal(erase[4],0);
});
test('omitted new settings retain the original renderer and layer',()=>{
    assert.equal(MATERIAL_DEFAULTS.renderer_version,'legacy');assert.equal(MATERIAL_DEFAULTS.layer_mode,'replacement');
    assert.equal(MATERIAL_DEFAULTS.moire_on,false);
});
test('linked sparkle sliders update from either source; enabling the link uses depth',()=>{
    assert.deepEqual(linkedSparklePatch({sparkle_bright:45},true,100),{sparkle_bright:45,sparkle_depth:45});
    assert.deepEqual(linkedSparklePatch({sparkle_depth:20},true,100),{sparkle_bright:20,sparkle_depth:20});
    assert.deepEqual(linkedSparklePatch({sparkle_link:true},false,80),{sparkle_link:true,sparkle_bright:80});
    assert.deepEqual(linkedSparklePatch({sparkle_bright:45},false,100),{sparkle_bright:45});
});
