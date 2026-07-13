import { NavLink, Route, Routes } from 'react-router-dom';
import { ConnectionBanner } from './components/ConnectionBanner';
import { LiveDataProvider } from './state/LiveDataContext';
import { Alerts } from './pages/Alerts';
import { BracketOrder } from './pages/BracketOrder';
import { Chain } from './pages/Chain';
import { Charts } from './pages/Charts';
import { Dashboard } from './pages/Dashboard';
import { MaxPain } from './pages/MaxPain';
import { OrderTicket } from './pages/OrderTicket';
import { PortfolioSimulator } from './pages/PortfolioSimulator';
import { Positions } from './pages/Positions';
import { ProfitCalc } from './pages/ProfitCalc';
import { StrategyBuilder } from './pages/StrategyBuilder';
import { UnusualWhales } from './pages/UnusualWhales';
import { Watchlist } from './pages/Watchlist';

export default function App() {
  return (
    <LiveDataProvider>
      <ConnectionBanner />
      <nav className="nav-tabs">
        <NavLink to="/" end>Dashboard</NavLink>
        <NavLink to="/chain">Chain</NavLink>
        <NavLink to="/order">Order Ticket</NavLink>
        <NavLink to="/profit-calc">Profit Calculator</NavLink>
        <NavLink to="/portfolio-simulator">Portfolio Simulator</NavLink>
        <NavLink to="/bracket">Bracket Order</NavLink>
        <NavLink to="/strategy">Strategy Builder</NavLink>
        <NavLink to="/max-pain">Max Pain</NavLink>
        <NavLink to="/unusual-whales">Unusual Whales</NavLink>
        <NavLink to="/positions">Positions</NavLink>
        <NavLink to="/charts">Charts</NavLink>
        <NavLink to="/watchlist">Watchlist</NavLink>
        <NavLink to="/alerts">Alerts</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/chain" element={<Chain />} />
        <Route path="/order" element={<OrderTicket />} />
        <Route path="/profit-calc" element={<ProfitCalc />} />
        <Route path="/portfolio-simulator" element={<PortfolioSimulator />} />
        <Route path="/bracket" element={<BracketOrder />} />
        <Route path="/strategy" element={<StrategyBuilder />} />
        <Route path="/max-pain" element={<MaxPain />} />
        <Route path="/unusual-whales" element={<UnusualWhales />} />
        <Route path="/positions" element={<Positions />} />
        <Route path="/charts" element={<Charts />} />
        <Route path="/watchlist" element={<Watchlist />} />
        <Route path="/alerts" element={<Alerts />} />
      </Routes>
    </LiveDataProvider>
  );
}
