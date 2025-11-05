#!/usr/bin/env python3

import re
from datetime import datetime

def test_date_filtering():
    """Test the date filtering logic with various filenames"""
    
    test_files = [
        "2025-07-09 15-06-29.mp3",  # Should skip (before 8/26)
        "2025-07-18 13-37-13.mp3",  # Should skip (before 8/26)
        "2025-07-30 11-43-02.mp3",  # Should skip (before 8/26)
        "2025-08-05 11-36-25.mp3",  # Should skip (before 8/26)
        "2025-08-12 10-04-13.mp3",  # Should skip (before 8/26)
        "2025-08-25 23-59-59.mp3",  # Should skip (before 8/26)
        "2025-08-26 00-00-00.mp3",  # Should process (on 8/26)
        "2025-08-27 09-59-54 product standup Wednesday.mp3",  # Should process (after 8/26)
        "2025-08-28 09-57-02 Product Standup Thursday.mp3",  # Should process (after 8/26)
        "random_audio_file.mp3",  # No date - would fall back to file creation time
    ]
    
    cutoff_date = datetime(2025, 8, 26)
    date_pattern = r'(\d{4})-(\d{2})-(\d{2})'
    
    print("Testing date filtering logic:")
    print(f"Cutoff date: {cutoff_date.strftime('%Y-%m-%d')}")
    print("-" * 50)
    
    for filename in test_files:
        match = re.search(date_pattern, filename)
        
        if match:
            year, month, day = map(int, match.groups())
            recording_date = datetime(year, month, day)
            
            if recording_date < cutoff_date:
                status = "SKIP"
                reason = f"recorded {recording_date.strftime('%Y-%m-%d')} < cutoff"
            else:
                status = "PROCESS"
                reason = f"recorded {recording_date.strftime('%Y-%m-%d')} >= cutoff"
        else:
            status = "FALLBACK"
            reason = "no date in filename - check file creation time"
        
        print(f"{status:8} | {filename:50} | {reason}")

if __name__ == "__main__":
    test_date_filtering()