### Allow non-root user to run systemd service

* create dir `.config/systemd/user`
* put your `fancy.service` to `.config/systemd/user`
* `systemctl --user daemon-reload`
* `systemctl --user enable fancy`

### Check journalctl 
`journalctl --user -u fancy`

### Usage
`systemctl --user restart fancy`

### .service example
```bash
[Unit]
Description=
[Service]
ExecStart=/home/venv/path/entry/point
[Install]
WantedBy=default.target
```

### Links
* [systemd: Grant an unprivileged user permission to alter one specific service](https://serverfault.com/questions/841099/systemd-grant-an-unprivileged-user-permission-to-alter-one-specific-service)
* [How to allow a user to use journalctl to see user-specific systemd service logs?](https://serverfault.com/questions/806469/how-to-allow-a-user-to-use-journalctl-to-see-user-specific-systemd-service-logs)

