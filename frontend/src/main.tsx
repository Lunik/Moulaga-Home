import React from 'react'
import ReactDOM from 'react-dom/client'
import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'

import App from './App'
import './index.css'
import { registerPwa } from './pwa'

registerPwa()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      networkMode: 'always',
      retry: (failureCount) => onlineManager.isOnline() && failureCount < 3,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
