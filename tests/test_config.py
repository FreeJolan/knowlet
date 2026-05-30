from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from knowlet.config import KnowletConfig, load_config, save_config


def test_save_config_parallel_writers_do_not_share_tempfile(tmp_path):
    writer_count = 12
    barrier = threading.Barrier(writer_count)

    def write_config(index: int) -> None:
        cfg = KnowletConfig()
        cfg.llm.model = f"gpt-test-{index}"
        barrier.wait(timeout=5)
        save_config(tmp_path, cfg)

    with ThreadPoolExecutor(max_workers=writer_count) as pool:
        futures = [pool.submit(write_config, index) for index in range(writer_count)]
        for future in futures:
            future.result(timeout=5)

    loaded = load_config(tmp_path)
    assert loaded.llm.model.startswith("gpt-test-")
    assert list((tmp_path / ".knowlet").glob("*.tmp")) == []
