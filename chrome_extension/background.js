
chrome.commands.onCommand.addListener((command) => {
  if (command === "send-selection") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0] && tabs[0].url) {
        // Chrome strictly blocks scripts from running on its own settings pages
        if (tabs[0].url.startsWith("chrome://") || tabs[0].url.startsWith("edge://")) {
            console.warn("Cannot extract text from restricted browser pages.");
            return;
        }
        
        chrome.scripting.executeScript({
          target: { tabId: tabs[0].id },
          function: grabTextAndBeamIt
        }).catch(err => console.error("Extraction error: ", err));
      }
    });
  }
});

function grabTextAndBeamIt() {
  const selectedText = window.getSelection().toString().trim();
  
  if (selectedText) {
    // Send it to the Python overlay's local background server
    fetch('http://localhost:65432/inject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: selectedText })
    })
    .then(response => console.log("Beamed successfully!"))
    .catch(err => console.error('Overlay server not running or connection refused.', err));
  } else {
    console.log("No text highlighted to send.");
  }
}
