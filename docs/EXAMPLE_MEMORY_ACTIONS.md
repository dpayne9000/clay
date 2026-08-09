      {
        "id": "memory_tags",
        "type": "deriveTags",
        "contentKey": "turn_summary",
        "maxTags": 6,
        "includedData": ["turn_summary"]
      },
      {
        "id": "memory_saved",
        "type": "writeMemory",
        "namespace": "system-editor",
        "content": "turn_summary",
        "tagsKey": "memory_tags",
        "includedData": ["turn_summary", "memory_tags"]
      }