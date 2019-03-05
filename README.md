### ImageMagick

Install and take care about right permissions in `/etc/ImageMagick-ver/policy.xml`

### Font
Install Ubuntu font

download to ~/.fonts
https://fonts.google.com/specimen/Ubuntu

`fc-cache -f -v`

`fc-list | grep Ubuntu # to check`

### virtualenv
```
python -m venv ./.venv/getcam
pip intall -r requirements.txt
pip install -e ../getcam/
``` 