"""

FLATNUTS
=========

Directional sampling within regions.

Work in unit cube space. assume a step size
1) starting from a live point
2) choose a random direction based on whitened space metric
3) for forward and backward direction:
  3.1) find distance where leaving spheres (surely outside)
  3.2) bisect the step that leads out of the likelihood threshold
  3.3) can we scatter forward?
     - if we stepped outside the unit cube, use normal to the parameter(s) we stepped out from
     - if gradient available, use it at first outside point
     - for each sphere that contains the last inside point:
       - resize so that first outside point is on the surface, get tangential vector there
         (this vector is just the difference between sphere center and last inside point)
       - compute reflection of direction vector with tangential plane
     - choose a forward reflection at random (if any)
  3.4) test if next point is inside again. If yes, continue NUTS

NUTS: 
  - alternatingly double the number of steps to the forward or backward side
  - build a tree; terminate when start and end directions are not forward any more
  - choose a end point at random out of the sequence

If the number of steps on any straight line is <10 steps, make step size smaller
If the number of steps on any straight line is >100 steps, make step size slightly bigger

Parameters:
 - Number of NUTS tracks (has to be user-tuned to ensure sufficiently independent samples; starting from 1, look when Z does not change anymore)
 - Step size (self-adjusting)

Benefit of this algorithm:
 - insensitive to step size
 - insensitive to dimensionality (sqrt scaling), better than slice sampling
 - takes advantage of region information, can accelerate low-d problems as well
Drawbacks:
 - inaccurate reflections degrade dimensionality scaling
 - more complex to implement than slice sampling

"""


import numpy as np
from numpy.linalg import norm
import matplotlib.pyplot as plt

def nearest_box_intersection_line(ray_origin, ray_direction, fwd=True):
    """
    Compute intersection of a line (ray) and a unit box (0:1 in all axes)
    
    Based on
    http://www.iquilezles.org/www/articles/intersectors/intersectors.htm
    
    ray_origin: starting point of line
    ray_direction: line direction vector
    
    returns: p, t, i
    p: intersection point
    t: intersection point distance from ray_origin in units in ray_direction
    i: axes which change direction at pN
    
    To continue forward traversing at the reflection point use:
    
    while True:
        # update current point x
        x, _, i = box_line_intersection(x, v)
        # change direction
        v[i] *= -1
    
    """
    
    # make sure ray starts inside the box
    
    assert (ray_origin >= 0).all(), ray_origin
    assert (ray_origin <= 1).all(), ray_origin
    
    # step size
    with np.errstate(divide='ignore', invalid='ignore'):
        m = 1./ ray_direction
        n = m * (ray_origin - 0.5)
        k = np.abs(m) * 0.5
        # line coordinates of intersection
        # find first intersecting coordinate
        if fwd:
            t2 = -n + k
            tF = np.nanmin(t2)
            iF = np.where(t2 == tF)[0]
        else:
            t1 = -n - k
            tF = np.nanmax(t1)
            iF = np.where(t1 == tF)[0]
    
    pF = ray_origin + ray_direction * tF
    eps = 1e-6
    assert (pF >= -eps).all(), pF
    assert (pF <= 1 + eps).all(), pF
    pF[pF < 0] = 0
    pF[pF > 1] = 1
    return pF, tF, iF

def box_line_intersection(ray_origin, ray_direction):
    """ return intersections of a line with the unit cube, in both sides """
    pF, tF, iF = nearest_box_intersection_line(ray_origin, ray_direction, fwd=True)
    pN, tN, iN = nearest_box_intersection_line(ray_origin, ray_direction, fwd=False)
    if tN > tF or tF < 0:
        assert False, "no intersection"
    return (pN, tN, iN), (pF, tF, iF)

def linear_steps_with_reflection(ray_origin, ray_direction, t, wrapped_dims=None):
    """ go t steps in direction ray_direction from ray_origin,
    but reflect off the unit cube if encountered. In any case, 
    the distance should be t * ray_direction.
    
    Returns (new_point, new_direction)
    """
    if t == 0:
        return ray_origin, ray_direction
    if t < 0:
        new_point, new_direction = linear_steps_with_reflection(ray_origin, -ray_direction, -t)
        return new_point, -new_direction
    
    if wrapped_dims is not None:
        reflected = np.zeros(len(ray_origin), dtype=bool)
    
    tleft = 1.0 * t
    while True:
        p, t, i = nearest_box_intersection_line(ray_origin, ray_direction, fwd=True)
        #print(p, t, i, ray_origin, ray_direction)
        assert np.isfinite(p).all()
        assert t >= 0, t
        if tleft <= t: # stopping before reaching any border
            assert np.all(ray_origin + tleft * ray_direction >= 0), (ray_origin, tleft, ray_direction)
            assert np.all(ray_origin + tleft * ray_direction <= 1), (ray_origin, tleft, ray_direction)
            return ray_origin + tleft * ray_direction, ray_direction
        # go to reflection point
        ray_origin = p
        assert np.isfinite(ray_origin).all(), ray_origin
        # reflect
        ray_direction = ray_direction.copy()
        if wrapped_dims is None:
            ray_direction[i] *= -1
        else:
            # if we already once bumped into that (wrapped) axis, 
            # do not continue but return this as end point
            if np.logical_and(reflected[i], wrapped_dims[i]).any():
                return ray_origin, ray_direction
            
            # note which axes we already flipped
            reflected[i] = True
            
            # in wrapped axes, we can keep going. Otherwise, reflects
            ray_direction[i] *= np.where(wrapped_dims[i], 1, -1)
            
            # in the i axes, we should wrap the coordinates
            assert np.logical_or(np.isclose(ray_origin[i], 1), np.isclose(ray_origin[i], 0)).all(), ray_origin[i]
            ray_origin[i] = np.where(wrapped_dims[i], 1 - ray_origin[i], ray_origin[i])
        
        assert np.isfinite(ray_direction).all(), ray_direction
        # reduce remaining distance
        tleft -= t

def get_sphere_tangents(sphere_center, edge_point):
    """ Assume a sphere centered at sphere_center with radius 
    so that edge_point is on the surface. At edge_point, in 
    which direction does the normal vector point? 
    
    Returns vector pointing to the sphere center.
    """
    arrow = sphere_center - edge_point
    return arrow / norm(arrow, axis=1).reshape((-1, 1))
    
def get_sphere_tangent(sphere_center, edge_point):
    """ Assume a sphere centered at sphere_center with radius 
    so that edge_point is on the surface. At edge_point, in 
    which direction does the normal vector point? 
    
    Returns vector pointing to the sphere center.
    """
    arrow = sphere_center - edge_point
    return arrow / norm(arrow)

def reflect(v, normal):
    """ reflect vector v off a normal vector, return new direction vector """
    return v - 2 * (normal * v).sum() * normal

def distances(l, o, r=1):
    """
    Compute sphere-line intersection
    
    l: direction vector (line starts at 0)
    o: center of sphere (coordinate vector)
    r: radius of sphere (float)
    
    returns (tpos, tneg), the positive and negative coordinate along the l vector where r is intersected.
    If no intersection, throws AssertError
    """
    loc = (l * o).sum()
    osqrnorm = (o**2).sum()
    #print(loc.shape, loc.shape, osqrnorm.shape)
    rootterm =  loc**2 - osqrnorm + r**2
    # make sure we are crossing the sphere
    assert (rootterm > 0).all(), rootterm 
    return -loc + rootterm**0.5, -loc - rootterm**0.5

def isunitlength(vec):
    """
    Verifies that vec is of unit length.
    """
    assert np.isclose(norm(vec), 1), norm(vec)

def angle(a, b):
    """
    Compute the dot product between vectors a and b
    The arccos of it would give an actual angle.
    """
    #anorm = (a**2).sum()**0.5
    #bnorm = (b**2).sum()**0.5
    return (a*b).sum() # / anorm / bnorm

def extrapolate_ahead(di, xj, vj):
    """
    Make di steps of size vj from xj.
    Reflect off unit cube if necessary.
    """
    return linear_steps_with_reflection(xj, vj, di)

class SamplingPath(object):
    def __init__(self, x0, v0, L0):
        self.reset(x0, v0, L0)
    
    def add(self, i, x0, v0, L0):
        self.points.append((i, x0, v0, L0))
    
    def reset(self, x0, v0, L0):
        self.points = []
        self.add(0, x0, v0, L0)
        self.fwd_possible = True
        self.rwd_possible = True
    
    def plot(self, **kwargs):
        x = np.array([x for i, x, v, L in sorted(self.points)])
        p, = plt.plot(x[:,0], x[:,1], 'o ', **kwargs)
        ilo, _, _, _ = min(self.points)
        ihi, _, _, _ = max(self.points)
        x = np.array([self.interpolate(i)[0] for i in range(ilo, ihi+1)])
        kwargs['color'] = p.get_color()
        plt.plot(x[:,0], x[:,1], 'o-', ms=4, mfc='None', **kwargs)
    
    def interpolate(self, i):
        """
        Interpolate a point on the path
        
        Given our sparsely sampled track (stored in .points),
        potentially with reflections, 
        extract the corrdinates of the point with index i.
        That point may not have been evaluated.
        """
        
        points_before = [(j, xj, vj, Lj) for j, xj, vj, Lj in self.points if j <= i]
        points_after  = [(j, xj, vj, Lj) for j, xj, vj, Lj in self.points if j >= i]
        
        # check if the point after is really after i
        if len(points_after) == 0 and not self.fwd_possible:
            # the path cannot continue, and i does not exist.
            #print("    interpolate_point %d: the path cannot continue fwd, and i does not exist." % i)
            j, xj, vj, Lj = max(points_before)
            return xj, vj, Lj, False
        
        # check if the point before is really before i
        if len(points_before) == 0 and not self.rwd_possible:
            # the path cannot continue, and i does not exist.
            k, xk, vk, Lk = min(points_after)
            #print("    interpolate_point %d: the path cannot continue rwd, and i does not exist." % i)
            return xk, vk, Lk, False
        
        if len(points_before) == 0 or len(points_after) == 0:
            #return None, None, None, False
            raise KeyError("can not extrapolate outside path")
        
        j, xj, vj, Lj = max(points_before)
        k, xk, vk, Lk = min(points_after)
        
        #print("    interpolate_point %d between %d-%d" % (i, j, k))
        if j == i: # we have this exact point in the chain
            return xj, vj, Lj, True
        
        assert not k == i # otherwise the above would be true too
        
        # expand_to_step explores each reflection in detail, so
        # any points with change in v should have j == i
        # therefore we can assume:
        # assert (vj == vk).all()
        # this ^ is not true, because reflections on the unit cube can
        # occur, and change v without requiring a intermediate point.
        
        # j....i....k
        xl1, vj1 = extrapolate_ahead(i - j, xj, vj)
        xl2, vj2 = extrapolate_ahead(i - k, xk, vk)
        assert np.allclose(xl1, xl2), (xl1, xl2, i, j, k, xj, vj, xk, vk)
        assert np.allclose(vj1, vj2), (xl1, vj1, xl2, vj2, i, j, k, xj, vj, xk, vk)
        xl = xl1
        
        #xl = interpolate_between_two_points(i, xj, j, xk, k)
        # the new point is then just a linear interpolation
        #w = (i - k) * 1. / (j - k)
        #xl = xj * w + (1 - w) * xk
        
        return xl, vj, None, True
        
    def extrapolate(self, i):
        """
        Advance beyond the current path, extrapolate from the end point.
        
        i: index on path.
        
        returns coordinates of the new point.
        """
        if i >= 0:
            j, xj, vj, Lj = max(self.points)
            deltai = i - j
            assert deltai > 0, ("should be extrapolating", i, j)
        else:
            j, xj, vj, Lj = min(self.points)
            deltai = i - j
            assert deltai < 0, ("should be extrapolating", i, j)
        
        newpoint = extrapolate_ahead(deltai, xj, vj)
        #print((deltai, j, xj, vj), newpoint)
        return newpoint



class ContourSamplingPath(object):
    def __init__(self, samplingpath, region, transform, likelihood, Lmin):
        self.samplingpath = samplingpath
        self.points = self.samplingpath.points
        self.transform = transform
        self.likelihood = likelihood
        self.Lmin = Lmin
        self.region = region
        self.ncalls = 0
    
    def add_if_above_threshold(self, i, x, v):
        # x, v = self.samplingpath.extrapolate(i)
        p = self.transform(x)
        L = self.likelihood(p)
        self.ncalls += 1
        if L > self.Lmin:
            print("    accepted", x, "as point %d" % i)
            self.samplingpath.add(i, x, v, L)
            return True
        else:
            print("    rejected", x)
            return False
    
    def gradient(self, reflpoint, v, plot=False):
        """
        reflpoint: 
            point outside the likelihood contour, reflect there
        v:
            previous direction vector
        return:
            gradient vector (normal of ellipsoid)
        
        Finds spheres enclosing the reflpoint, and chooses their mean
        as the direction to go towards. If no spheres enclose the 
        reflpoint, use nearest sphere.
        
        v is not used, because that would break detailed balance.
        
        Considerations:
           - in low-d, we want to focus on nearby live point spheres
             The border traced out is fairly accurate, at least in the
             normal away from the inside.
             
           - in high-d, reflpoint is contained by all live points,
             and none of them point to the center well. Because the
             sampling is poor, the "region center" position
             will be very stochastic.
        """
        if plot:
            plt.plot(reflpoint[0], reflpoint[1], '+ ', color='k', ms=10)
        
        # check which the reflections the ellipses would make
        region = self.region
        bpts = region.transformLayer.transform(reflpoint.reshape((1,-1)))
        dist = ((bpts - region.unormed)**2).sum(axis=1)
        nearby = dist < region.maxradiussq
        assert nearby.shape == (len(region.unormed),), (nearby.shape, len(region.unormed))
        if not nearby.any():
            nearby = dist == dist.min()
        sphere_centers = region.u[nearby,:]

        tsphere_centers = region.unormed[nearby,:]
        nlive, ndim = region.unormed.shape
        assert tsphere_centers.shape[1] == ndim, (tsphere_centers.shape, ndim)
        
        # choose mean among those points
        tsphere_center = tsphere_centers.mean(axis=0)
        assert tsphere_center.shape == (ndim,), (tsphere_center.shape, ndim)
        tt = get_sphere_tangent(tsphere_center, bpts.flatten())
        assert tt.shape == tsphere_center.shape, (tt.shape, tsphere_center.shape)
        
        # convert back to u space
        sphere_center = region.transformLayer.untransform(tsphere_center)
        t = region.transformLayer.untransform(tt * 1e-3 + tsphere_center) - sphere_center
        
        if plot:
            tt_all = get_sphere_tangent(tsphere_centers, bpts)
            t_all = region.transformLayer.untransform(tt_all * 1e-3 + tsphere_centers) - sphere_centers
            plt.plot(sphere_centers[:,0], sphere_centers[:,1], 'o ', mfc='None', mec='b', ms=10, mew=1)
            for si, ti in zip(sphere_centers, t_all):
                plt.plot([si[0], ti[0] * 1000 + si[0]], [si[1], ti[1] * 1000 + si[1]], color='gray', alpha=0.5)
            plt.plot(sphere_center[0], sphere_center[1], '^ ', mfc='None', mec='g', ms=10, mew=3)
            plt.plot([sphere_center[0], t[0] * 1000 + sphere_center[0]], [sphere_center[1], t[1] * 1000 + sphere_center[1]], color='gray')

        # compute new vector
        normal = t / norm(t)
        isunitlength(normal)
        assert normal.shape == t.shape, (normal.shape, t.shape)
        
        return normal
        
class StepSampler(object):
    """
    Find a new point with a series of small steps
    """
    def __init__(self, contourpath, epsilon=0.1, plot=False):
        """
        Starts a sampling track from x in direction v.
        is_inside is a function that returns true when a given point is inside the volume
        
        epsilon gives the step size in direction v.
        samples, if given, helps choose the gradient -- To be removed
        plot: if set to true, make some debug plots
        """
        self.fwd_possible = True
        self.rwd_possible = True
        self.epsilon_too_large = False
        self.contourpath = contourpath
        self.points = self.contourpath.points
        self.epsilon = epsilon
        self.nevals = 0
        self.nreflections = 0
        self.plot = plot
    
    def reverse(self, reflpoint, v, plot=False):
        """
        Reflect off the surface at reflpoint going in direction v
        
        returns the new direction.
        """
        normal = self.contourpath.gradient(reflpoint, v, plot=plot)
        if normal is None:
            #assert False
            return -v
        
        vnew = v - 2 * angle(normal, v) * normal
        print("    new direction:", vnew)
        assert vnew.shape == v.shape, (vnew.shape, v.shape)
        assert np.isclose(norm(vnew), norm(v)), (vnew, v, norm(vnew), norm(v))
        #isunitlength(vnew)
        if plot:
            plt.plot([reflpoint[0], (-v + reflpoint)[0]], [reflpoint[1], (-v + reflpoint)[1]], '-', color='k', lw=2, alpha=0.5)
            plt.plot([reflpoint[0], (vnew + reflpoint)[0]], [reflpoint[1], (vnew + reflpoint)[1]], '-', color='k', lw=3)
        return vnew
    
    def expand_to_step(self, i, plot=False):
        """
        Run steps forward or backward to step i (can be positive or 
        negative, 0 is the starting point) 
        """
        if i > 0 and self.fwd_possible:
            starti, startx, startv, _ = max(self.points)
            for j in range(starti, i):
                if not self.expand_onestep(plot=plot):
                    break
        elif self.rwd_possible:
            starti, startx, startv, _ = min(self.points)
            for j in range(starti, i, -1):
                if not self.expand_onestep(fwd=False, plot=plot):
                    break
    
    def expand_onestep(self, fwd=True, plot=True):
        """
        Make a single step forward (if fwd=True) or backwards)
        from the current state (stored in self.points)
        """
        
        if fwd:
            starti, startx, startv, _ = max(self.points)
            sign = 1
        else:
            starti, startx, startv, _ = min(self.points)
            sign = -1
        
        j = starti + 1 * sign
        xj, v = self.contourpath.samplingpath.extrapolate(j)
        #print('extrapolated point:', xj, v)
        accepted = self.contourpath.add_if_above_threshold(j, xj, v)
        
        if not accepted:
            # We stepped outside, so now we need to reflect
            #print("we stepped outside, need to reflect", xj)
            if plot: plt.plot(xj[0], xj[1], 'xr')
            vk = self.reverse(xj, v * sign, plot=plot) * sign
            #print("  outside; reflecting velocity", v, vk)
            xk, vk = extrapolate_ahead(sign, xj, vk)
            self.nreflections += 1
            #print("  trying new point,", xk)
            accepted = self.contourpath.add_if_above_threshold(j, xk, vk)
            if not accepted:
                #print("failed to recover. Terminating side", xk)
                if plot: plt.plot(xk[0], xk[1], 's', mfc='None', mec='r', ms=10)
                if fwd:
                    self.contourpath.samplingpath.fwd_possible = False
                else:
                    self.contourpath.samplingpath.rwd_possible = False
                return False
        
        return True
    
    def path_plot(self, color='blue'):
        self.points.sort()
        x0 = [x[0] for i, x, v in self.points]
        x1 = [x[1] for i, x, v in self.points]
        plt.plot(x0, x1, 'o-', color=color, mfc='None', ms=8)
        x0 = [x[0] for i, x, v in self.points if i == 0]
        x1 = [x[1] for i, x, v in self.points if i == 0]
        plt.plot(x0, x1, 's', mec='k', mfc='None', ms=10)

class BisectSampler(StepSampler):
    """
    Step sampler that does not require each step to be evaluated
    """
    def bisect(self, left, leftx, leftv, right, offseti):
        """
        Bisect to find first point outside
        left is the index of the point still inside
        leftx is its coordinate
        
        right is the index of the point already outside
        rightx is its coordinate
        
        offseti is an offset to the indices to be applied before storing the point
        
        """
        # left is always inside
        # right is always outside
        while True:
            mid = (right + left) // 2
            #print("bisect: interval %d-%d-%d (+%d)" % (left,mid,right, offseti))
            if mid == left or mid == right:
                break
            midx, midv = extrapolate_ahead(mid, leftx, leftv)

            accepted = self.contourpath.add_if_above_threshold(mid+offseti, midx, midv)
            if accepted:
                #print("   inside.  updating interval %d-%d" % (mid, right))
                left = mid
            else:
                #print("   outside. updating interval %d-%d" % (left, mid))
                right = mid
        return right
    
    def expand_to_step(self, i, continue_after_reflection=True, plot=False):
        """
        Run steps forward or backward to step i (can be positive or 
        negative, 0 is the starting point), if possible.
        
        Tries to jump ahead if possible, and bisect otherwise.
        This avoid having to make all steps in between.
        """
        if i > 0:
            sign = 1
            fwd = True
            starti, startx, startv, _ = max(self.points)
            if starti >= i:
                # already done
                return
        else:
            sign = -1
            fwd = False
            starti, startx, startv, _ = min(self.points)
            if starti <= i:
                # already done
                return

        deltai = i - starti
        
        if     fwd and not self.contourpath.samplingpath.fwd_possible or \
           not fwd and not self.contourpath.samplingpath.rwd_possible:
            # we are stuck now, and have to hope that the 
            # caller does not expect us to have filled that point
            return
        
        #print("  trying to expand to", i, " which is %d away" % deltai)
        xi, v = self.contourpath.samplingpath.extrapolate(i)
        accepted = self.contourpath.add_if_above_threshold(i, xi, v)
        if not accepted:
            # left is inside, right is outside
            #print("  starting bisecting at 0(inside)..%d(outside)" % deltai, startx, startv)
            outsidei = self.bisect(0, startx, startv, deltai, offseti=starti)
            self.nreflections += 1
            xj, startv = extrapolate_ahead(outsidei, startx, startv)
            #print("  bisecting gave reflection point", outsidei, "(+", starti, ")", xj, startv)
            if self.plot: plt.plot(xj[0], xj[1], 'xr')
            vk = self.reverse(xj, startv * sign, plot=plot) * sign
            #print("  reversing there", vk)
            xk, vk = extrapolate_ahead(sign, xj, vk)
            #print("  making one step from", xj, vk, '-->', xk, vk)
            self.nreflections += 1
            #print("  trying new point,", xk)
            accepted = self.contourpath.add_if_above_threshold(outsidei+starti, xk, vk)
            if accepted:
                if continue_after_reflection or angle(vk, startv) > 0:
                    self.expand_to_step(i) # recurse
            else:
                #print("  failed to recover. Terminating side", xk)
                if plot: plt.plot(xk[0], xk[1], 's', mfc='None', mec='r', ms=10)
                if fwd:
                    self.contourpath.samplingpath.fwd_possible = False
                else:
                    self.contourpath.samplingpath.rwd_possible = False
                return False

class NUTSSampler(BisectSampler):
    """
    No-U-turn sampler (NUTS) on flat surfaces.
    
    see nuts_step function.
    """
    
    def nuts_step(self, plot=False):
        """
        Alternatingly doubles the number of steps to forward and backward 
        direction (which may include reflections, see StepSampler and
        BisectSampler).
        When track returns (start and end of tree point toward each other),
        terminates and returns a random point on that track.
        """
        # this is (0, x0, v0) in both cases
        left_state = self.points[0][:3]
        right_state = self.points[0][:3]
        
        # pre-explore a bit (until reflection or the number of steps)
        # this avoids doing expand_to_step with small step numbers later
        self.expand_to_step(-10, continue_after_reflection=False, plot=plot)
        self.expand_to_step(+10, continue_after_reflection=False, plot=plot)
        print(self.points)
        stop = False
        
        j = 0 # tree depth
        validrange = (0, 0)
        while not stop:
            rwd = np.random.randint(2) == 1
            if j > 7:
                print("NUTS step: tree depth %d, %s" % (j, "rwd" if rwd else "fwd"))
            if rwd:
                #print("  building rwd tree... ")
                self.expand_to_step(left_state[0] - 2**j, plot=plot)
                left_state, _, newrange, newstop = self.build_tree(left_state, j, rwd=rwd)
            else:   
                #print("  building fwd tree...")
                self.expand_to_step(right_state[0] + 2**j)
                _, right_state, newrange, newstop = self.build_tree(right_state, j, rwd=rwd)
            
            if not newstop:
                validrange = (min(validrange[0], newrange[0]), max(validrange[1], newrange[1]))
                #print("  new range: %d..%d" % (validrange[0], validrange[1]))
            
            ileft, xleft, vleft = left_state
            iright, xright, vright = right_state
            if self.plot: plt.plot([xleft[0], xright[0]], [xleft[1] + (j+1)*0.02, xright[1] + (j+1)*0.02], '--')
            #if j > 5:
            #   print("  first-to-last arrow", ileft, iright, xleft, xright, xright-xleft, " velocities:", vright, vleft)
            #   print("  stopping criteria: ", newstop, angle(xright-xleft, vleft), angle(xright-xleft, vright))
            stop = newstop or angle(xright-xleft, vleft) <= 0 or angle(xright-xleft, vright) <= 0
            
            j = j + 1
            if j > 3:
                # check whether both ends of the tree are at the end of the path
                if validrange[0] < min(self.points)[0] and validrange[1] > max(self.points)[0]:
                    print("Stopping stuck NUTS")
                    print("starting point was: ", self.points[0])
                    break
                #if j > 7:
                #   print("starting point was: ", self.points[0])
                #   print("Stopping after %d levels" % j)
                #   break
            
        print("sampling between", validrange)
        return self.sample_chain_point(validrange[0], validrange[1])
    
    def sample_chain_point(self, a, b):
        """
        Gets a point on the track between a and b (inclusive)
        """
        if self.plot: 
            for i in range(a, b+1):
                xi, vi, Li, onpath = self.contourpath.samplingpath.interpolate(i)
                plt.plot(xi[0], xi[1], '+', color='g')
        while True:
            i = np.random.randint(a, b+1)
            xi, vi, Li, onpath = self.contourpath.samplingpath.interpolate(i)
            #print("NUTS sampled point:", xi, (i, a, b))
            if not onpath:
                continue
            #if (i, xi, vi) not in self.points:
            return xi, Li
    
    def build_tree(self, startstate, j, rwd):
        """
        Build sub-trees of depth j in direction rwd
        
        startstate: (i, x, v) state information of first node
        j: int height of the tree
        rwd: bool whether we go backward
        """
        if j == 0:
            # base case: go forward one step
            i = startstate[0] + (-1 if rwd else +1)
            #self.expand_to_step(i)
            #print("  build_tree@%d" % i, rwd, self.contourpath.samplingpath.fwd_possible, self.contourpath.samplingpath.rwd_possible)
            xi, vi, Li, onpath = self.contourpath.samplingpath.interpolate(i)
            if self.plot: plt.plot(xi[0], xi[1], 'x', color='gray')
            # this is a good state, so return it
            return (i, xi, vi), (i, xi, vi), (i,i), False
        
        # recursion-build the left and right subtrees
        (ileft, xleft, vleft), (iright, xright, vright), rangea, stopa = self.build_tree(startstate, j-1, rwd)
        if stopa:
            #print("  one subtree already terminated; returning")
            #plt.plot([xright[0], xleft[0]], [xright[1], xleft[1]], ':', color='navy')
            return (ileft, xleft, vleft), (iright, xright, vright), (ileft,iright), stopa
        if rwd:
            # go back
            (ileft, xleft, vleft), _, rangeb, stopb = self.build_tree((ileft, xleft, vleft), j-1, rwd)
        else:
            _, (iright, xright, vright), rangeb, stopb = self.build_tree((iright, xright, vright), j-1, rwd)
        #print("  subtree termination at %d" % j, stopa, stopb, angle(xright-xleft, vleft), angle(xright-xleft, vright), angle(vleft, vright))
        #plt.plot([xright[0], xleft[0]], [xright[1], xleft[1]], ':', color='gray')
        # NUTS criterion: start to end vector must point in the same direction as velocity at end-point
        # additional criterion: start and end velocities must point in opposite directions
        stop = stopa or stopb or angle(xright-xleft, vleft) <= 0 or angle(xright-xleft, vright) <= 0 or angle(vleft, vright) <= 0
        return (ileft, xleft, vleft), (iright, xright, vright), (ileft,iright), stop

