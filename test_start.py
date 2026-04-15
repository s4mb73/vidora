import requests
import hashlib
import urllib3
urllib3.disable_warnings()

pw = open('C:/vidora/pass.txt').read().strip()
h = hashlib.md5(pw.encode()).hexdigest()

# Sign in
r = requests.post('https://api.multilogin.com/user/signin',
    json={'email': 'innoviteecom@gmail.com', 'password': h},
    headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
token = r.json()['data']['token']
print('Signed in OK')

# Start quick profile
payload = {
    'browser_type': 'stealthfox',
    'os_type': 'windows',
    'automation': 'selenium',
    'is_headless': False,
    'parameters': {
        'flags': {
            'audio_masking': 'mask',
            'fonts_masking': 'mask',
            'geolocation_masking': 'mask',
            'geolocation_popup': 'prompt',
            'graphics_masking': 'mask',
            'graphics_noise': 'mask',
            'localization_masking': 'mask',
            'media_devices_masking': 'mask',
            'navigator_masking': 'mask',
            'ports_masking': 'mask',
            'proxy_masking': 'disabled',
            'screen_masking': 'mask',
            'timezone_masking': 'mask',
            'webrtc_masking': 'mask'
        },
        'fingerprint': {}
    }
}

print('Starting browser...')
r2 = requests.post(
    'http://127.0.0.1:45001/api/v2/profile/quick',
    json=payload,
    headers={'Accept': 'application/json', 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
    stream=True,
    timeout=60
)
print('Status:', r2.status_code)
print('Response:', r2.text[:500])