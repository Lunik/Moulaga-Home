self.addEventListener('activate', (event) => {
  event.waitUntil(caches.delete('moulaga-visual-data-v1'))
})
