##### Store APScheduler jobs not in memory
Issues with task serialization (pickle) so seems it does not worth to try hard since not frequent service restarts. And we could sacrifice some img getting tasks.

##### Limit ffmpeg memory usage
Seems it is impossible so I've introduced resize option for that reason
  