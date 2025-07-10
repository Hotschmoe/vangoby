import { h } from 'preact';
import type { FunctionComponent } from 'preact';
import { useState } from 'preact/hooks';

interface NFTData {
  holders: number;
  totalEth: number;
  ethPerHolder: number;
}

interface ResultsData {
  X: NFTData;
  Y: NFTData;
}

const App: FunctionComponent = () => {
  const [contractX, setContractX] = useState('');
  const [contractY, setContractY] = useState('');
  const [results, setResults] = useState<ResultsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async () => {
    if (!contractX || !contractY) {
      setError('Please enter both contract addresses');
      return;
    }

    try {
      setLoading(true);
      setError('');
      setResults(null);
      
      const res = await fetch(`/api/nft-data?contractX=${contractX}&contractY=${contractY}`);
      
      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(errorText || 'Failed to fetch data');
      }
      
      const data = await res.json();
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error fetching data');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="input-group">
        <input 
          value={contractX} 
          onInput={(e: Event) => setContractX((e.target as HTMLInputElement).value)} 
          placeholder="Contract X Address (e.g., 0x1234...)" 
        />
        <input 
          value={contractY} 
          onInput={(e: Event) => setContractY((e.target as HTMLInputElement).value)} 
          placeholder="Contract Y Address (e.g., 0x5678...)" 
        />
        <button onClick={handleSubmit} disabled={loading}>
          {loading ? 'Loading...' : 'Compare Collections'}
        </button>
      </div>

      {error && <div style={{ color: 'red', marginBottom: '20px' }}>{error}</div>}

      {results && (
        <div className="results">
          <div className="results-card">
            <h2>Collection X</h2>
            <p><strong>Holders:</strong> {results.X.holders}</p>
            <p><strong>Total ETH:</strong> {results.X.totalEth.toFixed(2)} ETH</p>
            <p><strong>ETH/Holder:</strong> {results.X.ethPerHolder.toFixed(4)} ETH</p>
          </div>
          <div className="results-card">
            <h2>Collection Y</h2>
            <p><strong>Holders:</strong> {results.Y.holders}</p>
            <p><strong>Total ETH:</strong> {results.Y.totalEth.toFixed(2)} ETH</p>
            <p><strong>ETH/Holder:</strong> {results.Y.ethPerHolder.toFixed(4)} ETH</p>
          </div>
        </div>
      )}
    </div>
  );
};

export default App; 