#!/usr/bin/env node
'use strict';

const ytSearch = require('yt-search');

async function main() {
  const query = process.argv.slice(2).join(' ').trim();
  if (!query) {
    process.stdout.write(JSON.stringify({ videos: [] }));
    return;
  }
  const result = await ytSearch(query);
  const videos = (result.videos || []).slice(0, 12).map((v) => ({
    id: String(v.videoId || ''),
    title: String(v.title || ''),
    url: String(v.url || (v.videoId ? `https://www.youtube.com/watch?v=${v.videoId}` : '')),
    author: String(v.author?.name || ''),
    duration: String(v.timestamp || ''),
    seconds: Number(v.seconds || 0),
    thumbnail: String(v.thumbnail || v.image || ''),
    views: Number(v.views || 0),
    ago: String(v.ago || '')
  })).filter((v) => v.id && v.url);
  process.stdout.write(JSON.stringify({ videos }));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exitCode = 1;
});
