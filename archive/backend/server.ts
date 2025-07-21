import { ethers } from 'ethers';
import { serve } from 'bun';

// Configure ethers with a public provider (will be replaced with local node later)
const provider = new ethers.JsonRpcProvider('https://eth-mainnet.g.alchemy.com/v2/demo'); // Demo key for minimal functionality

// Function to get NFT data for a contract
async function getNFTData(contractAddress: string) {
  // This is a simplified implementation
  // In a real application, we would:
  // 1. Use ethers to query all token holders
  // 2. Get ETH balance for each holder
  // 3. Calculate averages and totals
  
  try {
    // Mock data for demonstration purposes
    const holders = Math.floor(Math.random() * 1000) + 100;
    const totalEth = parseFloat((Math.random() * 100).toFixed(2));
    return {
      holders,
      totalEth,
      ethPerHolder: parseFloat((holders / totalEth).toFixed(4))
    };
    
    // Actual implementation would be:
    /*
    const contract = new ethers.Contract(
      contractAddress,
      ['function ownerOf(uint256) view returns (address)'],
      provider
    );
    
    // Get holders (simplified implementation)
    const holders = new Set<string>();
    // In production, use Transfer events or dedicated API
    
    // Calculate total ETH
    let totalEth = 0n;
    for (const holder of holders) {
      const balance = await provider.getBalance(holder);
      totalEth += balance;
    }
    
    const ethPerHolder = holders.size > 0 ? Number(totalEth) / 1e18 / holders.size : 0;
    
    return {
      holders: holders.size,
      totalEth: Number(totalEth) / 1e18,
      ethPerHolder
    };
    */
  } catch (error) {
    console.error(`Error fetching data for contract ${contractAddress}:`, error);
    throw new Error(`Failed to fetch data for contract ${contractAddress}`);
  }
}

// Create and export the server
export const server = Bun.serve({
  port: 3002,
  async fetch(req) {
    const url = new URL(req.url);
    
    // API endpoint for NFT data
    if (url.pathname === '/api/nft-data') {
      try {
        const contractX = url.searchParams.get('contractX');
        const contractY = url.searchParams.get('contractY');
        
        if (!contractX || !contractY) {
          return new Response('Missing contract addresses', { status: 400 });
        }
        
        const [dataX, dataY] = await Promise.all([
          getNFTData(contractX),
          getNFTData(contractY)
        ]);
        
        return new Response(
          JSON.stringify({ X: dataX, Y: dataY }),
          { 
            headers: { 'Content-Type': 'application/json' },
            status: 200 
          }
        );
      } catch (error) {
        console.error('API error:', error);
        return new Response(
          error instanceof Error ? error.message : 'Server error',
          { status: 500 }
        );
      }
    }
    
    // The index.ts file will handle static file serving
    return new Response('Not found', { status: 404 });
  },
});

console.log(`Backend server running at http://localhost:${server.port}`); 