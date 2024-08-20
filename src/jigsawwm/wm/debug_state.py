import pickle
import logging
import os

logger = logging.getLogger()
logging.basicConfig(level=logging.DEBUG)
logger.info("hello")

DEFAULT_STATE_PATH = os.path.join(os.getenv("LOCALAPPDATA"), "jigsawwm", "wm.state")
with open(DEFAULT_STATE_PATH, "rb") as f:
    try:
        virtdesk_states = pickle.load(f)
        for vdid, vdstate in virtdesk_states.items():
            logger.info("virt_desk: %s", vdid)
            for monitor, monitor_state in vdstate.monitor_states.items():
                logger.info("  monitor: %s", monitor.name)
                for ws in monitor_state.workspaces:
                  logger.info("    workspace: %s", ws.name)
                  for win in ws.windows:
                      logger.info("      %s", win)
                  for win in ws.tilable_windows:
                      logger.info("        tilable: %s", win)
        logger.info("state: %s", virtdesk_states)
    except: # pylint: disable=bare-except
        logger.exception("load windows states error", exc_info=True)