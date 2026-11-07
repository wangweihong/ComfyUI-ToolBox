import {test} from 'node:test';
import assert from 'node:assert/strict';
import {encodeText,decodeText,retainLineEndings,preparePackage} from '../web/js/skill_package_editor.mjs';

test('text package helpers retain Unicode, BOM, indentation, variables and CRLF',()=>{
    for(const text of ['\ufeff# 标题\r\n\r\n    {{variable}}\r\n','  plain\n\n','']) {
        assert.equal(decodeText(encodeText(text)),text);
        assert.equal(Buffer.from(encodeText(text),'base64').toString('utf8'),text);
    }
});

test('binary and malformed UTF-8 files are not editable as text',()=>{
    assert.equal(decodeText(Buffer.from([0,255,1]).toString('base64')),null);
    assert.equal(decodeText(Buffer.from([255,254]).toString('base64')),null);
    assert.equal(decodeText('!'),null);
});

test('main file imports keep CRLF when textarea normalizes line endings',()=>{
    assert.equal(retainLineEndings('# Skill\n\n    raw\n','# Skill\r\n\r\n    raw\r\n'),'# Skill\r\n\r\n    raw\r\n');
    assert.equal(retainLineEndings('edited\n','original\r\n'),'edited\n');
});

test('legacy mixed records retain standalone body as a file without changing originals',()=>{
    const initial={content:'旧正文\r\n',files:[{path:'content.md',data:encodeText('Other file')}]};
    const result=preparePackage(initial);
    assert.equal(result.primary,'_content.md');
    assert.equal(decodeText(result.files[1].data),'旧正文\r\n');
    assert.equal(initial.files.length,1);
    assert.match(result.note,/旧记录/);
    assert.equal(preparePackage({content:'text only',files:[]}).files.length,0);
});
