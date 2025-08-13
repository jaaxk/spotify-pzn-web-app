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
  
    let pollingInterval = null;
  
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
      const btn = document.createElement('button');
      btn.textContent = 'Find similar';
      btn.style.marginLeft = '8px';
      btn.onclick = async () => {
        const simRes = await fetch(`/api/similar/${userId}/${track.id}`);
        const sims = await simRes.json();
        let sHtml = 'Top similar:\n';
        sims.forEach(s => {
          sHtml += `${s.name} — ${s.artist} (score=${(s.similarity).toFixed(3)})\n`;
        });
        alert(sHtml);
      };
      li.appendChild(btn);
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
  