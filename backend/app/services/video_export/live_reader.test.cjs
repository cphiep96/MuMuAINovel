const {test}=require('node:test');const assert=require('node:assert/strict');
const {sameReading}=require('./live_reader.cjs');
test('literal text verification tolerates case and punctuation but rejects added or changed words',()=>{
 assert.equal(sameReading('Xin chào, An!','Xin chào An.'),true);
 assert.equal(sameReading('Xin chào An. Tôi sẽ đọc truyện.','Xin chào An.'),false);
 assert.equal(sameReading('Lâm đã lên bờ','Lâm chưa lên bờ'),false);
 assert.equal(sameReading('','Xin chào'),false);
});
