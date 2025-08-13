// main.js
document.addEventListener('DOMContentLoaded', function() {
    const params = new URLSearchParams(window.location.search);
    const userId = params.get('user_id');
    if (!userId) {
      document.body.innerHTML = '<p>Missing user_id in URL. Please login again.</p>';
      return;
    }
  
    const updateBtn = document.getElementById('update-library-btn');
    const encodedList = document.getElementById('encoded-list');
    const progressDiv = document.getElementById('progress');
    const progressText = document.getElementById('progress-text');
    const progressFill = document.getElementById('progress-fill');
  const searchInput = document.getElementById('track-search');
  const searchResults = document.getElementById('search-results');
  const playlistProgressDiv = document.getElementById('playlist-progress');
  const playlistProgressText = document.getElementById('playlist-progress-text');
  const playlistProgressFill = document.getElementById('playlist-progress-fill');
  const spotifyFrame = document.getElementById('spotify-frame');
  
  let pollingInterval = null;
  let playlistPollingInterval = null;
  
    async function loadEncoded() {
      try {
        const res = await fetch(`/api/encoded_tracks/${userId}`);
        const data = await res.json();
        encodedList.innerHTML = '';
        data.forEach(t => {
          addTrackToList(t);
        });
      } catch (error) {
        console.error('Error loading encoded tracks:', error);
        encodedList.innerHTML = '<li>Error loading tracks</li>';
      }
    }

    function addTrackToList(track) {
      const li = document.createElement('li');
      li.textContent = `${track.name} — ${track.artist}`;
      encodedList.appendChild(li);
    }

    async function pollTaskStatus(taskId) {
      try {
        const response = await fetch(`/api/task_status/${taskId}`);
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        console.log('Task status:', data); // Debug logging
        
        const progress = data.progress;
        if (!progress) {
          progressText.textContent = `Task status: ${data.status}`;
          return data.status;
        }
        
        if (progress.status === 'processing') {
          progressText.textContent = `Processing ${progress.index}/${progress.total}: ${progress.track.name} — ${progress.track.artist}`;
          const pct = Math.round((progress.index / progress.total) * 100);
          progressFill.style.width = `${pct}%`;
        } else if (progress.status === 'encoded') {
          progressText.textContent = `Encoded ${progress.index}/${progress.total}: ${progress.track.name}`;
          const pct = Math.round((progress.index / progress.total) * 100);
          progressFill.style.width = `${pct}%`;
          
          // Add the newly encoded track to the list in real-time
          if (progress.track) {
            addTrackToList(progress.track);
          }
        } else if (progress.status === 'finished') {
          progressText.textContent = `Finished: ${progress.message || `encoded ${progress.processed}/${progress.total}`}`;
          progressFill.style.width = '100%';
          
          // Stop polling and reset UI after a delay
          setTimeout(() => {
            stopPolling();
            resetUI();
            // Reload all tracks to ensure we have the latest data
            loadEncoded();
          }, 3000); // Show completion for 3 seconds
          
          return 'finished';
        }
        
        return data.status;
      } catch (error) {
        console.error('Error polling task status:', error);
        progressText.textContent = 'Error checking task status';
        return 'error';
      }
    }

    function startPolling(taskId) {
      // Clear any existing polling
      if (pollingInterval) {
        clearInterval(pollingInterval);
      }
      
      // Start polling every 2 seconds
      pollingInterval = setInterval(async () => {
        const status = await pollTaskStatus(taskId);
        
        // Stop polling if task is finished or failed
        if (status === 'finished' || status === 'failed' || status === 'error') {
          stopPolling();
          if (status === 'failed') {
            progressText.textContent = 'Task failed';
            setTimeout(resetUI, 3000);
          }
        }
      }, 2000); // Poll every 2 seconds
    }

    function stopPolling() {
      if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
      }
    }

    async function searchTracks(term) {
      const res = await fetch(`/api/search_tracks?q=${encodeURIComponent(term)}&limit=10`);
      if (!res.ok) throw new Error('Search failed');
      return res.json();
    }

    function renderSearchResults(items) {
      searchResults.innerHTML = '';
      items.forEach(item => {
        const li = document.createElement('li');
        li.textContent = `${item.name} — ${item.artist}`;
        li.style.cursor = 'pointer';
        li.onclick = () => selectSeedTrack(item);
        searchResults.appendChild(li);
      });
    }

    let searchDebounce = null;
    searchInput?.addEventListener('input', async (e) => {
      const term = e.target.value.trim();
      clearTimeout(searchDebounce);
      if (!term) {
        searchResults.innerHTML = '';
        return;
      }
      searchDebounce = setTimeout(async () => {
        try {
          const results = await searchTracks(term);
          renderSearchResults(results);
        } catch (err) {
          console.error(err);
        }
      }, 250);
    });

    async function selectSeedTrack(track) {
      try {
        // Start playlist generation
        const res = await fetch(`/api/generate_playlist?user_id=${parseInt(userId)}&seed_track_id=${track.id}`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to start playlist task');
        const data = await res.json();
        const taskId = data.task_id;

        // Show playlist progress UI
        playlistProgressDiv.style.display = 'block';
        playlistProgressText.textContent = 'Starting playlist generation...';
        playlistProgressFill.style.width = '0%';

        startPlaylistPolling(taskId);
      } catch (err) {
        console.error(err);
        alert('Failed to start playlist generation');
      }
    }

    async function pollPlaylistTaskStatus(taskId) {
      try {
        const response = await fetch(`/api/task_status/${taskId}`);
        const data = await response.json();
        const p = data.progress || {};
        if (p.status === 'finding_similar') {
          playlistProgressText.textContent = 'Finding similar tracks...';
          playlistProgressFill.style.width = '20%';
        } else if (p.status === 'spotify_auth') {
          playlistProgressText.textContent = 'Authorizing with Spotify...';
          playlistProgressFill.style.width = '30%';
        } else if (p.status === 'creating_playlist') {
          playlistProgressText.textContent = p.message || 'Creating playlist...';
          playlistProgressFill.style.width = '60%';
        } else if (p.status === 'adding_tracks') {
          playlistProgressText.textContent = p.message || 'Adding tracks...';
          playlistProgressFill.style.width = '80%';
        } else if (data.status === 'finished' || p.status === 'finished') {
          const result = p.playlist_id ? p : (data.progress || {});
          playlistProgressText.textContent = `Playlist ready`;
          playlistProgressFill.style.width = '100%';
          if (result && result.embed_url) {
            spotifyFrame.src = result.embed_url;
          }
          setTimeout(stopPlaylistPolling, 2000);
          return 'finished';
        } else if (data.status === 'failed' || p.status === 'failed') {
          playlistProgressText.textContent = p.message || 'Playlist task failed';
          setTimeout(stopPlaylistPolling, 2000);
          return 'failed';
        }
        return data.status;
      } catch (err) {
        console.error('Error polling playlist task', err);
        playlistProgressText.textContent = 'Error checking playlist task status';
        return 'error';
      }
    }

    function startPlaylistPolling(taskId) {
      if (playlistPollingInterval) clearInterval(playlistPollingInterval);
      playlistPollingInterval = setInterval(async () => {
        const status = await pollPlaylistTaskStatus(taskId);
        if (status === 'finished' || status === 'failed' || status === 'error') {
          stopPlaylistPolling();
        }
      }, 2000);
    }

    function stopPlaylistPolling() {
      if (playlistPollingInterval) {
        clearInterval(playlistPollingInterval);
        playlistPollingInterval = null;
      }
    }
  
    updateBtn.addEventListener('click', async () => {
      try {
        // Disable button to prevent multiple clicks
        updateBtn.disabled = true;
        updateBtn.textContent = 'Starting...';
        
        // Start job
        const res = await fetch(`/api/update_library?user_id=${parseInt(userId)}`, {
          method: 'POST'
        });
        
        if (!res.ok) {
          throw new Error(`HTTP error! status: ${res.status}`);
        }
        
        const data = await res.json();
        const taskId = data.task_id;
        
        // Show progress UI
        progressDiv.style.display = 'block';
        progressText.textContent = 'Starting task...';
        progressFill.style.width = '0%';
        
        // Start polling for task status
        startPolling(taskId);
        
        // Do initial status check
        await pollTaskStatus(taskId);
        
      } catch (error) {
        console.error('Error starting task:', error);
        progressText.textContent = `Error: ${error.message}`;
        resetUI();
      }
    });
    
    function resetUI() {
      updateBtn.disabled = false;
      updateBtn.textContent = 'Update my library';
      progressDiv.style.display = 'none';
    }
  
    // initial load
    loadEncoded();
  });
  