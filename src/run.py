#!/usr/bin/env python3

import sys
import logging
import subprocess
from pathlib import Path
from typing import List

from parameters import Parameters

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def build_potree_command(params: Parameters) -> List[str]:
    """Build PotreeConverter command from parameters"""
    # Use absolute path to help PotreeConverter find its resources
    cmd = ["/opt/PotreeConverter/PotreeConverter"]
    
    # Add source files/directories
    for source in params.source:
        cmd.append(source)
    
    # Add output directory if specified
    if params.outdir:
        cmd.extend(["-o", str(params.outdir)])
    
    # Add encoding
    if params.encoding != "DEFAULT":
        cmd.extend(["--encoding", params.encoding])
    
    # Add sampling method
    if params.method != "poisson":
        cmd.extend(["-m", params.method])
    
    # Add chunk method
    if params.chunk_method != "LASZIP":
        cmd.extend(["--chunkMethod", params.chunk_method])
    
    # Add attributes
    for attr in params.attributes:
        cmd.extend(["--attributes", attr])
    
    # Add boolean flags
    if params.keep_chunks:
        cmd.append("--keep-chunks")
    
    if params.no_chunking:
        cmd.append("--no-chunking")
    
    if params.no_indexing:
        cmd.append("--no-indexing")
    
    # Add page generation
    if params.generate_page:
        cmd.extend(["-p", params.generate_page])
    
    if params.title:
        cmd.extend(["--title", params.title])
    
    return cmd


def main():
    """Main execution function"""
    try:
        # Parse parameters
        params = Parameters()
        logger.info(f"Parameters: {params}")
        
        # Build command
        cmd = build_potree_command(params)
        logger.info(f"Executing: {' '.join(cmd)}")
        
        # Execute PotreeConverter
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # Print output
        print(result.stdout)
        
        logger.info("PotreeConverter completed successfully")
        return 0
        
    except subprocess.CalledProcessError as e:
        logger.error(f"PotreeConverter failed with exit code {e.returncode}")
        logger.error(f"Output: {e.stdout}")
        return e.returncode
        
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
