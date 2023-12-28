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
pip install -r requirements.txt
pip install -e ../getcam/
``` 

#### Change log
* Introduced resize option. Useful for large source images. It helps to save disk space and let us ability to make movies on poor hardware.

#### TODOs
* Add calculating of total disk usage in daily report
* Add timing for tasks execution, maybe add that to task report message